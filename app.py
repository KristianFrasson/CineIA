from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import google.generativeai as genai
import streamlit as st

APP_TITLE = "CineIA"
# The current key exposes the Gemini flash alias below in the available model list.
# The activity mentions gemini-1.5-flash, but this alias keeps the app runnable now.
MODEL_NAME = "gemini-flash-latest"
FEEDBACK_FILE = Path("feedback.csv")
GENRES = [
    "Ação",
    "Drama",
    "Sci-Fi",
    "Comédia",
    "Terror",
    "Documentário",
]


st.set_page_config(page_title=APP_TITLE, page_icon="🎬")


def configure_model() -> Any:
    """Configure Gemini using the Streamlit secret configured locally or in Cloud."""
    try:
        genai.configure(api_key=st.secrets["general"]["api_key"])
    except KeyError:
        st.error(
            "Chave da API ausente. Configure `.streamlit/secrets.toml` localmente "
            "ou cole o segredo em Streamlit Cloud em Settings -> Secrets."
        )
        st.stop()

    return genai.GenerativeModel(MODEL_NAME)


def build_prompt(genres: list[str], max_minutes: int, mood: str) -> str:
    selected_genres = ", ".join(genres) if genres else "qualquer gênero clássico"
    mood_clean = mood.strip()

    return f"""
Você é o CineIA, um curador inteligente de filmes.
Interprete as preferências abaixo e responda SOMENTE com JSON válido.
Não use markdown, não use texto fora do JSON e retorne exatamente 3 itens.

Formato obrigatório:
[
  {{"titulo": "Filme", "ano": 2024, "porque": "Justificativa curta"}},
  {{"titulo": "Filme", "ano": 2023, "porque": "Justificativa curta"}},
  {{"titulo": "Filme", "ano": 2022, "porque": "Justificativa curta"}}
]

Regras:
- Escolha filmes coerentes com os gêneros informados.
- Respeite o limite de duração de até {max_minutes} minutos.
- Explique por que cada filme combina com o mood do usuário.
- Não repita filmes.
- Não inclua introdução, conclusão, numeração ou comentários adicionais.

Preferências do usuário:
- Gêneros: {selected_genres}
- Tempo máximo: {max_minutes} minutos
- Mood: {mood_clean}
""".strip()


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def parse_recommendations(text: str) -> list[dict[str, Any]]:
    cleaned = strip_code_fences(text)

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        json_match = re.search(r"\[[\s\S]*\]", cleaned)
        if not json_match:
            return []
        try:
            payload = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            return []

    if isinstance(payload, dict):
        payload = (
            payload.get("filmes")
            or payload.get("recommendations")
            or payload.get("results")
            or []
        )

    if not isinstance(payload, list):
        return []

    recommendations: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        title = str(item.get("titulo") or item.get("title") or "").strip()
        year = item.get("ano") or item.get("year") or ""
        reason = str(item.get("porque") or item.get("motivo") or item.get("why") or "").strip()

        if title and reason:
            recommendations.append(
                {"titulo": title, "ano": year, "porque": reason}
            )

        if len(recommendations) == 3:
            break

    return recommendations if len(recommendations) == 3 else []


def append_feedback(mood: str, genres: list[str], max_minutes: int, feedback: str) -> None:
    genres_text = " | ".join(genres) if genres else "Nenhum gênero selecionado"
    mood_clean = mood.replace("\n", " ").strip()

    with FEEDBACK_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if file.tell() == 0:
            writer.writerow(["mood", "generos", "tempo_maximo", "feedback"])
        writer.writerow([mood_clean, genres_text, max_minutes, feedback])


if "recommendations" not in st.session_state:
    st.session_state.recommendations = []
if "raw_response" not in st.session_state:
    st.session_state.raw_response = ""
if "result_signature" not in st.session_state:
    st.session_state.result_signature = None
if "feedback_notice" not in st.session_state:
    st.session_state.feedback_notice = None


st.title("🎬 CineIA: Seu Próximo Filme")
st.markdown(
    "Descubra 3 filmes alinhados aos seus gêneros favoritos, ao tempo disponível "
    "e ao seu mood atual."
)

with st.sidebar:
    st.header("Preferências")
    selected_genres = st.multiselect(
        "Escolha os gêneros clássicos:",
        GENRES,
        help="Selecione um ou mais gêneros para orientar a recomendação.",
    )
    max_minutes = st.slider("Tempo máximo do filme (minutos):", 60, 240, 120)
    mood = st.text_area(
        "Mood momentâneo:",
        placeholder="Ex.: quero algo leve, inspirador e com uma boa reviravolta.",
        help="Conte em poucas palavras como você está se sentindo ou o que quer assistir.",
    )

st.markdown(
    "Clique no botão abaixo para pedir ao Gemini 1.5 Flash uma seleção personalizada."
)
search_requested = st.button("Buscar Recomendações")

current_signature = {
    "genres": tuple(selected_genres),
    "max_minutes": max_minutes,
    "mood": mood.strip(),
}

if search_requested:
    if not mood.strip():
        st.warning("Descreva o mood momentâneo para continuar.")
    else:
        with st.spinner("Analisando catálogo cinematográfico..."):
            try:
                model = configure_model()
                prompt = build_prompt(selected_genres, max_minutes, mood)
                response = model.generate_content(prompt)
                response_text = getattr(response, "text", "") or ""

                if not response_text.strip():
                    raise RuntimeError("O Gemini não retornou texto para esta solicitação.")

                parsed = parse_recommendations(response_text)
                st.session_state.recommendations = parsed
                st.session_state.raw_response = response_text
                st.session_state.result_signature = current_signature
                st.session_state.feedback_notice = None

            except Exception as exc:
                st.error(
                    "Falha ao conectar ao Gemini ou ao processar a resposta. "
                    f"Detalhe técnico: {exc}"
                )


results_active = (
    st.session_state.result_signature == current_signature
    and bool(st.session_state.raw_response)
)

if results_active:
    st.markdown("---")
    st.subheader("🎯 Recomendações")

    if st.session_state.recommendations:
        for index, recommendation in enumerate(st.session_state.recommendations, start=1):
            year = recommendation.get("ano")
            year_text = f" ({year})" if year not in (None, "") else ""
            st.markdown(
                f"**{index}. {recommendation['titulo']}{year_text}**\n\n"
                f"{recommendation['porque']}"
            )
            if index < len(st.session_state.recommendations):
                st.markdown("---")

        st.markdown("### Feedback")
        st.caption("Ajude o CineIA a melhorar registrando sua avaliação desta rodada.")
        col_like, col_dislike = st.columns(2)

        with col_like:
            if st.button("👍 Gostei", key="feedback_like_button"):
                append_feedback(mood, selected_genres, max_minutes, "Gostei")
                st.session_state.feedback_notice = (
                    "success",
                    "Obrigado pelo feedback positivo!",
                )

        with col_dislike:
            if st.button("👎 Não gostei", key="feedback_dislike_button"):
                append_feedback(mood, selected_genres, max_minutes, "Não gostei")
                st.session_state.feedback_notice = (
                    "info",
                    "Feedback registrado. Vamos melhorar!",
                )

        if st.session_state.feedback_notice:
            level, message = st.session_state.feedback_notice
            if level == "success":
                st.success(message)
            else:
                st.info(message)
    else:
        st.error(
            "A resposta veio fora do formato esperado. O Gemini precisa devolver "
            "exatamente 3 itens em JSON válido."
        )
        with st.expander("Ver resposta bruta"):
            st.write(st.session_state.raw_response)

st.markdown("---")
st.markdown("### 📱 Acesse pelo celular")
st.markdown(
    "Escaneie o QR Code abaixo para abrir o CineIA no seu dispositivo mobile."
)
# Placeholder local: substitua esta imagem pelo QR Code real gerado depois do deploy.
# Quando o app estiver publicado no Streamlit Cloud, troque o arquivo por um QR Code
# que aponte para a URL final da aplicação.
st.image("qrcode.png", caption="Escaneie para abrir o CineIA", use_column_width=True)
