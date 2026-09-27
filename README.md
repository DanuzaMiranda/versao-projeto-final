# versão-projeto-final

Este repositório é a entrega final. A versão 2 junta o estudo de detecção de fraude a um assistente que conversa com a pessoa que recebeu o alerta.

A Vera ajuda uma pessoa a entender uma compra marcada no cartão e a escolher o próximo passo: reconhecer, contestar ou pedir bloqueio temporário. O caso usa a cliente fictícia Marina Alves e o Banco Aurora, também fictício. Os números saem dos arquivos em `data/`. Se a informação não está lá, a Vera diz isso.

Este repositório também guarda o estudo de detecção que motivou o tema. O notebook mede fraude rara em dados públicos. Ele não classifica a compra da Marina.

## Os 6 passos do desafio

| Passo | Onde está |
|-------|-----------|
| 1. Documentação | [docs/01-documentacao-agente.md](docs/01-documentacao-agente.md) |
| 2. Base de conhecimento | [docs/02-base-conhecimento.md](docs/02-base-conhecimento.md) e [data/](data/) |
| 3. Prompts | [docs/03-prompts.md](docs/03-prompts.md) e [src/prompts.py](src/prompts.py) |
| 4. Aplicação | [src/app.py](src/app.py) |
| 5. Avaliação | [docs/04-metricas.md](docs/04-metricas.md) e [src/avaliar.py](src/avaliar.py) |
| 6. Pitch | [docs/05-pitch.md](docs/05-pitch.md) — em andamento |

## Como conversar com a Vera

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt
python src/avaliar.py
streamlit run src/app.py
```

`python src/avaliar.py` roda 32 checagens no modo base, sem chave de API. Na última execução, 32 passaram.

O chat abre sem chave e guarda a conversa neste computador até você clicar em recomeçar. Para uma resposta generativa, copie `.env.example` para `.env` e preencha `OPENAI_API_KEY`. O mesmo formato aceita um endpoint local, como o Ollama, em `OPENAI_BASE_URL`. A fala do modelo só substitui a da base se todos os valores em reais já existirem na ficha calculada.

## O que a entrega cobre

| Pedido | Situação |
|--------|----------|
| Documentação, base, prompts e chat | Prontos em `docs/`, `data/` e `src/` |
| Resposta presa aos arquivos, com fonte | 26 conversas de teste |
| Próximo passo e memória da decisão | A contestação continua na fala seguinte e ao reabrir o chat |
| Trava do modelo generativo | Valor inventado e estorno aprovado são descartados |
| Pitch | Em andamento. O roteiro está em `docs/05-pitch.md`. Falta gravar o vídeo |

A compra em alerta da sessão é Eletrônicos Online INT, R$ 2.480,00, em 18/10/2025 às 02:14, no cartão final 4412.

---

# Estudo de detecção de fraude

Notebook de classificação para transações reais de cartão, com a fraude tratada como classe rara. O arquivo executado, com tabelas e curvas salvas, é o [`deteccao_fraude_cartao.ipynb`](deteccao_fraude_cartao.ipynb).

A base é a [Credit Card Fraud Detection](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud), do Machine Learning Group da Université Libre de Bruxelles: 284.807 transações de dois dias em setembro de 2013. O CSV não entra neste repositório. O notebook baixa o mesmo arquivo por um link direto.

## O problema

`Class = 1` é fraude e `Class = 0` é transação legítima. Na base há 492 fraudes, 0,1727% das linhas. As colunas `V1` a `V28` já são componentes de PCA; `Time` e `Amount` continuam na escala original.

A acurácia engana porque a classe legítima é quase a base inteira. Um modelo que nunca alerta fraude acerta 99,83% e encontra zero fraudes: no teste deste notebook, 56.864 acertos em 56.962 linhas, com recall 0.

| Métrica, só na classe fraude | O que responde |
|---|---|
| Recall | Das fraudes que existiam, quantas o alerta encontrou? |
| Precisão | Dos alertas emitidos, quantos eram fraude? |
| F1 | Qual é o equilíbrio entre achar fraude e não inundar a fila? |

Recall alto com precisão baixa enche a fila de um analista. Precisão alta com recall baixo deixa fraude passar. As duas entram juntas; a acurácia não decide o modelo.

## Preparação dos dados

1. Conferência da base: 284.807 linhas, 31 colunas, nenhum valor ausente, 492 fraudes.
2. Variáveis novas, calculadas linha a linha: `Amount_log = log(1 + Amount)` e `hora`, a hora do dia extraída de `Time`. A taxa de fraude não é plana ao longo do dia (por volta da hora 2 ela chega a 1,7%). Não há identificador de cartão, então não dá para montar sequência de transações do mesmo cliente.
3. Divisão estratificada: 64% treino, 16% validação e 20% teste. A fração de fraude fica em 0,173% nos três. A validação só escolhe o limiar. O teste é lido uma vez.
4. `StandardScaler` ajustado no treino e apenas aplicado na validação e no teste, em todas as colunas, inclusive nas que já vinham do PCA.

## Comparação dos modelos

Os três modelos usam peso para a classe rara (`class_weight="balanced"` na logística e na Random Forest; `scale_pos_weight` no XGBoost, 577,65 no treino). O modelo da entrega foi o de maior F1 na validação, não o de maior acurácia no teste.

Regra do limiar, igual para todos, decidida na validação: recall de fraude de pelo menos 0,80 e, entre esses limiares, o maior F1.

| Modelo | Limiar | Recall | Precisão | F1 | Acurácia |
|---|---:|---:|---:|---:|---:|
| XGBoost | 0,15 | 0,8776 | 0,7227 | 0,7926 | 0,9992 |
| Random Forest | 0,31 | 0,8776 | 0,6099 | 0,7197 | 0,9988 |
| Regressão logística | 0,97 | 0,8776 | 0,3755 | 0,5260 | 0,9973 |

Métricas no teste (98 fraudes). O XGBoost é o modelo escolhido.

No teste, esse limiar marca 86 fraudes e deixa 12 passarem. Há 33 alertas em transações legítimas. Recall 86/98, precisão 86/119.

A regressão logística, no limiar padrão 0,5, tem recall 0,9082 e F1 0,1148: o peso de classe empurra a probabilidade para cima e 0,5 alerta demais. O limiar 0,97 é o que recupera precisão. O `GridSearchCV` variou só o `C` e escolheu `C = 0,01` pelo F1 no limiar 0,5. Esse F1 de validação cruzada (0,122) não é a métrica final.

### Undersampling e oversampling

Testados só na regressão logística e só no treino. Validação e teste continuam na proporção real. O limiar de cada variante segue a mesma regra.

| Variante | Limiar | Recall | Precisão | F1 |
|---|---:|---:|---:|---:|
| Sem tratamento | 0,03 | 0,8265 | 0,5827 | 0,6835 |
| Peso de classe | 0,97 | 0,8776 | 0,3755 | 0,5260 |
| Oversampling | 0,97 | 0,8776 | 0,3373 | 0,4873 |
| Undersampling | 0,97 | 0,8776 | 0,2216 | 0,3539 |

Peso de classe, oversampling e undersampling empatam no recall (0,8776). O peso de classe é o melhor dos três em precisão e F1. Undersampling chega no mesmo recall com muito mais falso alerta, porque o treino fica com 630 linhas. A logística sem reamostragem, com limiar baixado para 0,03, tem recall um pouco menor e o melhor F1 deste grupo (0,6835). Nenhum desses quatro alcança o F1 do XGBoost.

## Limiar e o que o SHAP mostrou

O limiar do XGBoost ficou em **0,15**. Na validação, foi o maior F1 entre os pontos com recall de pelo menos 0,80. Ele não foi reajustado depois de ver o teste.

No mesmo teste, o limiar 0,5 daria recall 0,8367, precisão 0,8200 e F1 0,8283. O F1 seria maior e o recall continuaria acima de 0,80. A escolha permanece 0,15 porque a regra foi fechada na validação. Trocar o limiar depois de olhar o teste inflaria o resultado.

O SHAP foi calculado no XGBoost, numa amostra do teste. As variáveis com maior média de |SHAP| são `V14`, `V4`, `V12`, `V10` e `V8`. `hora` aparece em seguida, atrás desses componentes. `Amount_log` pesa na importância da árvore e menos no SHAP médio desta amostra.

Numa fraude com probabilidade prevista 1,0, os maiores empurrões para fraude foram `V14`, `V10`, `V12` e `V4` (SHAP positivo). `V8` puxou no sentido contrário e não bastou para mudar a decisão. Numa transação legítima cuja probabilidade ficou em 0,1496, logo abaixo do limiar, `V4` empurrou para fraude e `V8` e `V11` empurraram para legítima.

`V1`–`V28` não têm nome de negócio. O SHAP mostra qual componente pesou, não qual campo original do cliente isso era.

## O que mudou em relação ao roteiro da Expert

- A validação foi separada do teste. O limiar é escolhido num conjunto que o teste não vê.
- Undersampling e oversampling foram medidos na mesma logística, contra o peso de classe e contra o modelo sem tratamento. O recall de cada um está na tabela acima.
- `hora` foi criada a partir de `Time`. Sequência de transações do mesmo cartão não entra, porque a base não identifica o cartão.
- O `GridSearchCV` cobre só o `C` da regressão logística, com a ressalva de que esse F1 usa o limiar 0,5.

## Como reproduzir

O notebook já guarda as saídas. Para rodar de novo:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
jupyter nbconvert --to notebook --execute --inplace deteccao_fraude_cartao.ipynb
```

No macOS, o XGBoost precisa do OpenMP: `brew install libomp`.
