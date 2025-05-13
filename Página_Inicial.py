import os
import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime, timedelta
import plotly.express as px
from cachetools import TTLCache

# Configuração do cache (TTL de 300 segundos)
cache = TTLCache(maxsize=1, ttl=300)

# Configuração do cliente Supabase (usar variáveis de ambiente)
SUPABASE_URL = st.secrets["SUPABASE"]["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE"]["SUPABASE_KEY"]
# Validar URL e chave
if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Erro: SUPABASE_URL ou SUPABASE_KEY não estão definidos nas variáveis de ambiente.")
    st.stop()

# Inicializar cliente Supabase
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Erro ao inicializar o cliente Supabase: {e}")
    st.stop()

# CSS para quebra de linha no st.dataframe
st.markdown("""
<style>
    .stDataFrame table td {
        white-space: normal !important;
        word-wrap: break-word;
        max-width: 300px;
    }
</style>
""", unsafe_allow_html=True)

# Função para buscar produtos
def buscar_produto(codigoproduto=None, nomeproduto=None):
    cache_key = f"PCPRODUT_{codigoproduto}_{nomeproduto}"
    if cache_key in cache:
        return cache[cache_key]

    try:
        query = supabase.table("PCPRODUT").select("CODPROD, DESCRICAO, CODAUXILIAR, QTUNITCX")
        
        if codigoproduto and nomeproduto:
            query = query.or_(f"CODPROD.eq.{codigoproduto},DESCRICAO.ilike.%{nomeproduto}%")
        elif codigoproduto:
            query = query.eq("CODPROD", codigoproduto)
        elif nomeproduto:
            query = query.ilike("DESCRICAO", f"%{nomeproduto}%")

        response = query.execute()
        data = response.data

        if data:
            df = pd.DataFrame(data)
            df['DESCRICAO'] = df['DESCRICAO'].apply(lambda x: ''.join(c + '\u200B' for c in str(x)))
            df = df.rename(columns={
                "CODPROD": "CODIGOPRODUTO",
                "DESCRICAO": "PRODUTO",
                "CODAUXILIAR": "CODBARRA",
                "QTUNITCX": "QTCAIXA"
            })
            cache[cache_key] = df
        else:
            st.warning("Nenhum produto encontrado.")
            cache[cache_key] = pd.DataFrame()
            df = pd.DataFrame()

    except Exception as e:
        st.error(f"Erro ao buscar produtos do Supabase: {e}")
        cache[cache_key] = pd.DataFrame()
        df = pd.DataFrame()

    return cache[cache_key]

# Função para carregar dados de pedidos
@st.cache_data(show_spinner=False, ttl=300)
def carregar_dados():
    cache_key = "PCPEDC_data"
    if cache_key in cache:
        return cache[cache_key]

    try:
        all_data = []
        offset = 0
        limit = 1000

        required_columns = ['id', 'CODPROD', 'QT', 'NUMPED', 'DATA_PEDIDO', 'PVENDA', 'CONDVENDA', 
                           'CODUSUR', 'CODUSUR_N', 'CODFILIAL', 'CODPRACA', 'CODCLI', 'NOME_EMIT', 'DEVOLUCAO']

        while True:
            response = supabase.table("PCPEDC").select("*").range(offset, offset + limit - 1).execute()
            data = response.data
            if not data:
                break
            all_data.extend(data)
            offset += limit

        if all_data:
            df = pd.DataFrame(all_data)
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                st.error(f"Colunas ausentes nos dados retornados pela API: {missing_columns}")
                cache[cache_key] = pd.DataFrame()
                return pd.DataFrame()

            df['DATA_PEDIDO'] = pd.to_datetime(df['DATA_PEDIDO'], errors='coerce')
            df = df.dropna(subset=['DATA_PEDIDO'])

            for col in ['QT', 'PVENDA', 'CODUSUR_N']:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

            df['VLTOTAL'] = df['PVENDA'] * df['QT']
            df['VLTOTAL'] = df['VLTOTAL'].fillna(0)

            df = df[df['CODFILIAL'].isin(['1', '2'])]
            cache[cache_key] = df
        else:
            st.warning("Nenhum dado retornado pelo Supabase.")
            cache[cache_key] = pd.DataFrame()
            df = pd.DataFrame()

    except Exception as e:
        st.error(f"Erro ao buscar dados do Supabase: {e}")
        st.write(f"Detalhes do erro: {str(e)}")
        cache[cache_key] = pd.DataFrame()
        df = pd.DataFrame()

    return cache[cache_key]

# Função para formatar valores monetários
def formatar_valor(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# Funções de cálculo
def calcular_faturamento(data, hoje, ontem, semana_inicial, semana_passada_inicial):
    faturamento_hoje = data[data['DATA_PEDIDO'].dt.date == hoje.date()]['VLTOTAL'].sum()
    faturamento_ontem = data[data['DATA_PEDIDO'].dt.date == ontem.date()]['VLTOTAL'].sum()
    faturamento_semanal_atual = data[(data['DATA_PEDIDO'].dt.date >= semana_inicial.date()) & (data['DATA_PEDIDO'].dt.date <= hoje.date())]['VLTOTAL'].sum()
    faturamento_semanal_passada = data[(data['DATA_PEDIDO'].dt.date >= semana_passada_inicial.date()) & (data['DATA_PEDIDO'].dt.date < semana_inicial.date())]['VLTOTAL'].sum()
    return faturamento_hoje, faturamento_ontem, faturamento_semanal_atual, faturamento_semanal_passada

def calcular_quantidade_pedidos(data, hoje, ontem, semana_inicial, semana_passada_inicial):
    pedidos_hoje = data[data['DATA_PEDIDO'].dt.date == hoje.date()]['NUMPED'].nunique()
    pedidos_ontem = data[data['DATA_PEDIDO'].dt.date == ontem.date()]['NUMPED'].nunique()
    pedidos_semanal_atual = data[(data['DATA_PEDIDO'].dt.date >= semana_inicial.date()) & (data['DATA_PEDIDO'].dt.date <= hoje.date())]['NUMPED'].nunique()
    pedidos_semanal_passada = data[(data['DATA_PEDIDO'].dt.date >= semana_passada_inicial.date()) & (data['DATA_PEDIDO'].dt.date < semana_inicial.date())]['NUMPED'].nunique()
    return pedidos_hoje, pedidos_ontem, pedidos_semanal_atual, pedidos_semanal_passada

def calcular_comparativos(data, hoje, mes_atual, ano_atual):
    mes_anterior = mes_atual - 1 if mes_atual > 1 else 12
    ano_anterior = ano_atual if mes_atual > 1 else ano_atual - 1
    faturamento_mes_atual = data[(data['DATA_PEDIDO'].dt.month == mes_atual) & (data['DATA_PEDIDO'].dt.year == ano_atual)]['VLTOTAL'].sum()
    pedidos_mes_atual = data[(data['DATA_PEDIDO'].dt.month == mes_atual) & (data['DATA_PEDIDO'].dt.year == ano_atual)]['NUMPED'].nunique()
    faturamento_mes_anterior = data[(data['DATA_PEDIDO'].dt.month == mes_anterior) & (data['DATA_PEDIDO'].dt.year == ano_anterior)]['VLTOTAL'].sum()
    pedidos_mes_anterior = data[(data['DATA_PEDIDO'].dt.month == mes_anterior) & (data['DATA_PEDIDO'].dt.year == ano_anterior)]['NUMPED'].nunique()
    return faturamento_mes_atual, faturamento_mes_anterior, pedidos_mes_atual, pedidos_mes_anterior

def main():
    st.markdown("""
    <style>
        .st-emotion-cache-1ibsh2c {
            width: 100%;
            padding: 0rem 1rem 0rem;
            max-width: initial;
            min-width: auto;
        }
        .st-column {
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .card-container {
            display: flex;
            align-items: center;
            background-color: #302d2d;
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 10px;
            color: white;
            flex-direction: column;
            text-align: center;
            min-width: 180px;
            height: 160px;
        }
        .card-container img {
            width: 51px;
            height: 54px;
            margin-bottom: 5px;
        }
        .number {
            font-size: 20px;
            font-weight: bold;
            margin-top: 5px;
        }
    </style>
    """, unsafe_allow_html=True)

    st.title('Dashboard de Faturamento e Produtos')

    # Seção de busca de produtos
    st.markdown("### Busca de Produtos")
    col_prod1, col_prod2 = st.columns(2)
    with col_prod1:
        codigoproduto = st.text_input("Código do Produto")
    with col_prod2:
        nomeproduto = st.text_input("Nome do Produto")
    
    if st.button("Buscar Produto"):
        if codigoproduto or nomeproduto:
            produtos = buscar_produto(codigoproduto, nomeproduto)
            if not produtos.empty:
                st.dataframe(produtos)
            else:
                st.warning("Nenhum produto encontrado com os critérios fornecidos.")
        else:
            st.warning("Informe pelo menos o Código do Produto ou o Nome do Produto.")

    st.markdown("---")
    st.markdown("### Resumo de Vendas")

    with st.spinner("Carregando dados..."):
        data = carregar_dados()
    
    if not data.empty:
        col1, col2 = st.columns(2)
        with col1:
            filial_1 = st.checkbox("Filial 1", value=True)
        with col2:
            filial_2 = st.checkbox("Filial 2", value=True)

        filiais_selecionadas = []
        if filial_1:
            filiais_selecionadas.append('1')
        if filial_2:
            filiais_selecionadas.append('2')

        if not filiais_selecionadas:
            st.warning("Por favor, selecione pelo menos uma filial para exibir os dados.")
            return

        data_filtrada = data[data['CODFILIAL'].isin(filiais_selecionadas)]

        hoje = datetime.now()
        ontem = hoje - timedelta(days=1)
        semana_inicial = hoje - timedelta(days=hoje.weekday())
        semana_passada_inicial = semana_inicial - timedelta(days=7)

        faturamento_hoje, faturamento_ontem, faturamento_semanal_atual, faturamento_semanal_passada = calcular_faturamento(data_filtrada, hoje, ontem, semana_inicial, semana_passada_inicial)
        pedidos_hoje, pedidos_ontem, pedidos_semanal_atual, pedidos_semanal_passada = calcular_quantidade_pedidos(data_filtrada, hoje, ontem, semana_inicial, semana_passada_inicial)

        mes_atual = hoje.month
        ano_atual = hoje.year
        faturamento_mes_atual, faturamento_mes_anterior, pedidos_mes_atual, pedidos_mes_anterior = calcular_comparativos(data_filtrada, hoje, mes_atual, ano_atual)

        col1, col2, col3, col4, col5 = st.columns(5)

        def calcular_variacao(atual, anterior):
            if anterior == 0:
                return 100 if atual > 0 else 0
            return ((atual - anterior) / anterior) * 100
        
        def icone_variacao(valor):
            if valor > 0:
                return f"<span style='color: green;'>▲ {valor:.2f}%</span>"
            elif valor < 0:
                return f"<span style='color: red;'>▼ {valor:.2f}%</span>"
            else:
                return "0%"

        var_faturamento_mes = calcular_variacao(faturamento_mes_atual, faturamento_mes_anterior)
        var_pedidos_mes = calcular_variacao(pedidos_mes_atual, pedidos_mes_anterior)
        var_faturamento_hoje = calcular_variacao(faturamento_hoje, faturamento_ontem)
        var_pedidos_hoje = calcular_variacao(pedidos_hoje, pedidos_ontem)
        var_faturamento_semananterior = calcular_variacao(faturamento_semanal_atual, faturamento_semanal_passada)

        def grafico_pizza_variacao(labels, valores, titulo):
            valores = [abs(v) for v in valores]
            fig = px.pie(
                names=labels,
                values=valores,
                title=titulo,
                hole=0.4,
                color=labels,
                color_discrete_map={"Mês Atual": "green", "Mês Anterior": "red", "Hoje": "green", "Ontem": "red",
                                    "Semana Atual": "green", "Semana Passada": "red",
                                    "Pedidos Mês Atual": "green", "Pedidos Mês Passado": "red",
                                    "Pedidos Hoje": "green", "Pedidos Ontem": "red"}
            )
            fig.update_layout(margin=dict(t=30, b=30, l=30, r=30))
            return fig

        with col1:
            st.markdown(f"""
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/2460/2460494.png" alt="Ícone Hoje">
                    <span>Hoje:</span> 
                    <div class="number">{formatar_valor(faturamento_hoje)}</div>
                    <small>Variação: {icone_variacao(var_faturamento_hoje)}</small>
                </div>
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/3703/3703896.png" alt="Ícone Ontem">
                    <span>Ontem:</span> 
                    <div class="number">{formatar_valor(faturamento_ontem)}</div>
                </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown(f"""
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/4435/4435153.png" alt="Ícone Semana Atual">
                    <span>Semana Atual:</span> 
                    <div class="number">{formatar_valor(faturamento_semanal_atual)}</div>
                    <small>Variação: {icone_variacao(var_faturamento_semananterior)}</small>
                </div>
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/4435/4435153.png" alt="Ícone Semana Passada">
                    <span>Semana Passada:</span> 
                    <div class="number">{formatar_valor(faturamento_semanal_passada)}</div>
                </div>
            """, unsafe_allow_html=True)

        with col3:
            st.markdown(f"""
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/10535/10535844.png" alt="Ícone Mês Atual">
                    <span>Mês Atual:</span> 
                    <div class="number">{formatar_valor(faturamento_mes_atual)}</div>
                    <small>Variação: {icone_variacao(var_faturamento_mes)}</small>
                </div>
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/584/584052.png" alt="Ícone Mês Anterior">
                    <span>Mês Anterior:</span> 
                    <div class="number">{formatar_valor(faturamento_mes_anterior)}</div>
                </div>
            """, unsafe_allow_html=True)

        with col4:
            st.markdown(f"""
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/6632/6632848.png" alt="Ícone Pedidos Mês Atual">
                    <span>Pedidos Mês Atual:</span> 
                    <div class="number">{pedidos_mes_atual}</div>
                    <small>Variação: {icone_variacao(var_pedidos_mes)}</small>
                </div>
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/925/925049.png" alt="Ícone Pedidos Mês Anterior">
                    <span>Pedidos Mês Anterior:</span> 
                    <div class="number">{pedidos_mes_anterior}</div>
                </div>
            """, unsafe_allow_html=True)

        with col5:
            st.markdown(f"""
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/14018/14018701.png" alt="Ícone Pedidos Hoje">
                    <span>Pedidos Hoje:</span> 
                    <div class="number">{pedidos_hoje}</div>
                </div>
                <div class="card-container">
                    <img src="https://cdn-icons-png.flaticon.com/512/5220/5220625.png" alt="Ícone Pedidos Ontem">
                    <span>Pedidos Ontem:</span> 
                    <div class="number">{pedidos_ontem}</div>
                </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.plotly_chart(grafico_pizza_variacao(["Hoje", "Ontem"], [faturamento_hoje, faturamento_ontem], "Variação de Faturamento (Hoje x Ontem)"), use_container_width=True)
        with col2:
            st.plotly_chart(grafico_pizza_variacao(["Semana Atual", "Semana Passada"], [faturamento_semanal_atual, faturamento_semanal_passada], "Variação de Faturamento (Semana)"), use_container_width=True)
        with col3:
            st.plotly_chart(grafico_pizza_variacao(["Mês Atual", "Mês Anterior"], [faturamento_mes_atual, faturamento_mes_anterior], "Variação de Faturamento (Mês)"), use_container_width=True)
        with col4:
            st.plotly_chart(grafico_pizza_variacao(["Pedidos Mês Atual", "Pedidos Mês Passado"], [pedidos_mes_atual, pedidos_mes_anterior], "Variação de Pedidos (Mês)"), use_container_width=True)
        with col5:
            st.plotly_chart(grafico_pizza_variacao(["Pedidos Hoje", "Pedidos Ontem"], [pedidos_hoje, pedidos_ontem], "Variação de Pedidos (Hoje x Ontem)"), use_container_width=True)

        st.markdown("---")
        st.subheader("Comparação de Vendas por Mês e Ano")

        col_data1, col_data2 = st.columns(2)
        min_date = data_filtrada['DATA_PEDIDO'].min() if not data_filtrada.empty else pd.to_datetime("2024-01-01")
        max_date = data_filtrada['DATA_PEDIDO'].max() if not data_filtrada.empty else pd.to_datetime("2025-05-13")
        with col_data1:
            data_inicial = st.date_input("Data Inicial", value=pd.to_datetime("2024-04-08"), min_value=min_date, max_value=max_date)
        with col_data2:
            data_final = st.date_input("Data Final", value=max_date, min_value=min_date, max_value=max_date)

        if data_inicial > data_final:
            st.error("A data inicial não pode ser maior que a data final.")
            return

        df_periodo = data_filtrada[(data_filtrada['DATA_PEDIDO'].dt.date >= data_inicial) & 
                                   (data_filtrada['DATA_PEDIDO'].dt.date <= data_final)].copy()

        if not df_periodo.empty:
            df_periodo['Ano'] = df_periodo['DATA_PEDIDO'].dt.year
            df_periodo['Mês'] = df_periodo['DATA_PEDIDO'].dt.month

            vendas_por_mes_ano = df_periodo.groupby(['Ano', 'Mês']).agg(
                Valor_Total_Vendido=('VLTOTAL', 'sum')
            ).reset_index()

            fig = px.line(vendas_por_mes_ano, x='Mês', y='Valor_Total_Vendido', color='Ano',
                          title=f'Vendas por Mês ({data_inicial} a {data_final})',
                          labels={'Mês': 'Mês', 'Valor_Total_Vendido': 'Valor Total Vendido (R$)', 'Ano': 'Ano'},
                          markers=True)

            fig.update_layout(
                title_font_size=20,
                xaxis_title_font_size=16,
                yaxis_title_font_size=16,
                xaxis_tickfont_size=14,
                yaxis_tickfont_size=14,
                xaxis_tickangle=-45,
                xaxis=dict(tickmode='array', tickvals=list(range(1, 13)), ticktext=['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'])
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Nenhum dado disponível para o período selecionado.")
    else:
        st.warning("Nenhum dado disponível para exibição.")

if __name__ == "__main__":
    main()
