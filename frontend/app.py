from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import streamlit as st

from frontend.api_client import ApiClientError, PyMentorApiClient
from frontend.config import FrontendSettings
from frontend.state import (
    abandon_pending_submission,
    answer_widget_key,
    build_answer_payload,
    finish_submission,
    prepare_submission,
    resolve_document_scope,
)

PAGE_MATERIAL = "Materi"
PAGE_TUTOR = "Tutor"
PAGE_QUIZ = "Kuis"
PAGE_PROGRESS = "Progres"
PAGES = (PAGE_MATERIAL, PAGE_TUTOR, PAGE_QUIZ, PAGE_PROGRESS)


def get_api_client() -> PyMentorApiClient:
    injected = st.session_state.get("_api_client")
    if injected is not None:
        return injected
    settings = FrontendSettings.from_environment()
    client = PyMentorApiClient(settings)
    st.session_state["_api_client"] = client
    return client


def _api_read(label: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any] | None:
    try:
        with st.spinner(label):
            return operation()
    except ApiClientError as exc:
        st.error(str(exc))
        return None


def _show_action_error(exc: ApiClientError) -> None:
    st.error(str(exc))
    if exc.outcome_uncertain:
        st.warning(
            "Status operasi belum pasti. Periksa data terbaru sebelum mengulang. "
            "Frontend tidak melakukan retry otomatis."
        )


def _format_document(document: Mapping[str, Any]) -> str:
    return f"#{document['id']} · {document['source_name']}"


def _ready_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in documents if item.get("indexing_status") == "ready"]


def _document_scope_controls(
    ready: list[dict[str, Any]], *, key_prefix: str
) -> list[int] | None:
    mode = st.radio(
        "Cakupan materi",
        ("Semua dokumen siap", "Pilih dokumen tertentu", "Tanpa dokumen"),
        key=f"{key_prefix}_scope",
        help=(
            "Semua mengirim scope global (null); Tanpa dokumen mengirim array kosong. "
            "Keduanya memiliki arti berbeda di backend."
        ),
    )
    selected: list[int] = []
    if mode == "Pilih dokumen tertentu":
        options = [int(item["id"]) for item in ready]
        labels = {int(item["id"]): _format_document(item) for item in ready}
        selected = st.multiselect(
            "Dokumen siap yang dipakai",
            options,
            format_func=lambda value, document_labels=labels: document_labels[value],
            key=f"{key_prefix}_documents",
        )
        if not selected:
            st.info("Belum ada dokumen dipilih; request akan memakai corpus kosong.")
    elif mode == "Tanpa dokumen":
        st.info("Corpus sengaja dikosongkan. Backend tidak akan memperluasnya ke semua dokumen.")
    return resolve_document_scope(mode, selected)


def render_material(client: PyMentorApiClient) -> None:
    st.header("Materi")
    st.write("Unggah materi, pantau ingestion dan indexing, lalu periksa sumber serta chunk.")

    with st.form("upload_document", clear_on_submit=True):
        uploaded = st.file_uploader(
            "File UTF-8 TXT/MD atau PDF berbasis teks", type=["txt", "md", "pdf"]
        )
        upload_clicked = st.form_submit_button("Unggah materi", type="primary")
    if upload_clicked:
        if uploaded is None:
            st.warning("Pilih satu file terlebih dahulu.")
        else:
            try:
                with st.spinner("Mengunggah dan memproses materi…"):
                    result = client.upload_document(
                        filename=uploaded.name,
                        content=uploaded.getvalue(),
                        content_type=uploaded.type,
                    )
                if result.get("duplicate"):
                    st.info(f"File identik sudah ada sebagai dokumen #{result['id']}.")
                else:
                    st.success(f"Dokumen #{result['id']} berhasil diproses.")
            except ApiClientError as exc:
                _show_action_error(exc)

    page_number = int(st.number_input("Halaman daftar", min_value=1, value=1, step=1))
    page_size = 10
    page = _api_read(
        "Memuat daftar dokumen…",
        lambda: client.list_documents(limit=page_size, offset=(page_number - 1) * page_size),
    )
    if page is None:
        return
    documents = page.get("items", [])
    if not documents:
        st.info("Belum ada dokumen pada halaman ini.")
    else:
        st.caption(f"Menampilkan {len(documents)} dari {page.get('total', 0)} dokumen.")
    for document in documents:
        with st.expander(_format_document(document)):
            st.write(f"Status ingestion: **{document['status']}**")
            st.write(f"Status indexing: **{document['indexing_status']}**")
            st.caption(
                f"{document['source_type'].upper()} · {document['file_size_bytes']} byte · "
                f"{document['chunk_count']} chunk"
            )
            if document["indexing_status"] != "ready":
                if st.button("Index dokumen", key=f"index_{document['id']}", type="primary"):
                    try:
                        with st.spinner("Membuat embedding untuk seluruh chunk…"):
                            result = client.index_document(int(document["id"]))
                        label = "sudah siap" if result.get("idempotent") else "berhasil diindeks"
                        st.success(f"Dokumen #{document['id']} {label}.")
                    except ApiClientError as exc:
                        _show_action_error(exc)
            if st.button("Periksa status indexing", key=f"status_{document['id']}"):
                status = _api_read(
                    "Memeriksa status…",
                    lambda document_id=int(document["id"]): client.get_index_status(document_id),
                )
                if status is not None:
                    st.session_state["material_index_status"] = status

    status = st.session_state.get("material_index_status")
    if isinstance(status, dict):
        st.subheader("Status indexing terbaru")
        st.json(status, expanded=False)

    if documents:
        labels = {int(item["id"]): _format_document(item) for item in documents}
        inspect_id = st.selectbox(
            "Dokumen untuk inspeksi sumber",
            list(labels),
            format_func=lambda value, document_labels=labels: document_labels[value],
        )
        chunk_page = int(st.number_input("Halaman chunk", min_value=1, value=1, step=1))
        if st.button("Muat sumber dan chunk"):
            detail = _api_read("Memuat teks sumber…", lambda: client.get_document(int(inspect_id)))
            chunks = _api_read(
                "Memuat chunk…",
                lambda: client.list_chunks(
                    int(inspect_id), limit=10, offset=(chunk_page - 1) * 10
                ),
            )
            if detail is not None and chunks is not None:
                st.session_state["material_inspection"] = {"detail": detail, "chunks": chunks}

    inspection = st.session_state.get("material_inspection")
    if isinstance(inspection, dict):
        detail = inspection["detail"]
        st.subheader(f"Teks acuan · #{detail['id']}")
        reference = str(detail.get("reference_text", ""))
        st.code(reference[:5000], language=None, wrap_lines=True)
        if len(reference) > 5000:
            st.caption(
                "Tampilan teks acuan dibatasi 5.000 karakter; data lengkap tetap tersimpan di API."
            )
        for chunk in inspection["chunks"].get("items", []):
            page_label = f" · halaman {chunk['page_number']}" if chunk.get("page_number") else ""
            with st.expander(
                f"Chunk {chunk['chunk_index']} · karakter {chunk['start_char']}–{chunk['end_char']}"
                f"{page_label}"
            ):
                st.code(chunk["content"], language=None, wrap_lines=True)
                st.json(chunk.get("metadata", {}), expanded=False)


def render_tutor(client: PyMentorApiClient) -> None:
    st.header("Tutor")
    st.info(
        "Setiap pertanyaan berdiri sendiri. Tutor tidak menyimpan atau mengingat percakapan "
        "sebelumnya."
    )
    page = _api_read("Memuat dokumen siap…", lambda: client.list_documents(limit=100, offset=0))
    if page is None:
        return
    ready = _ready_documents(page.get("items", []))
    scope = _document_scope_controls(ready, key_prefix="tutor")

    with st.form("tutor_question"):
        question = st.text_area(
            "Pertanyaan Python",
            placeholder="Contoh: Mengapa fungsi tanpa return eksplisit menghasilkan None?",
            max_chars=2000,
        )
        top_k = st.slider("Jumlah sumber maksimum", min_value=1, max_value=8, value=4)
        ask = st.form_submit_button("Tanya tutor", type="primary")
    if ask:
        if not question.strip():
            st.warning("Pertanyaan tidak boleh kosong.")
        else:
            try:
                with st.spinner("Mencari sumber dan menyusun jawaban…"):
                    st.session_state["tutor_result"] = client.chat(
                        question=question,
                        top_k=top_k,
                        document_ids=scope,
                    )
                st.success("Respons tutor diterima.")
            except ApiClientError as exc:
                _show_action_error(exc)

    result = st.session_state.get("tutor_result")
    if isinstance(result, dict):
        st.subheader("Jawaban")
        if result.get("status") == "insufficient_context":
            st.warning(result.get("answer", "Materi belum cukup untuk menjawab."))
        else:
            st.markdown(str(result.get("answer", "")))
        citations = result.get("citations", [])
        if citations:
            st.subheader("Sumber")
        for citation in citations:
            page_label = (
                f", halaman {citation['page_number']}" if citation.get("page_number") else ""
            )
            with st.expander(
                f"{citation['reference_id']} · {citation['source_name']}{page_label}"
            ):
                st.caption(
                    f"Dokumen #{citation['document_id']}, chunk #{citation['chunk_id']}, "
                    f"karakter {citation['start_char']}–{citation['end_char']}"
                )
                st.code(citation["excerpt"], language=None, wrap_lines=True)


def _render_attempt_result(result: Mapping[str, Any], quiz: Mapping[str, Any] | None) -> None:
    st.subheader("Hasil percobaan")
    st.metric(
        "Skor latihan",
        f"{result['percentage']:.2f}%",
        help="Nilai dihitung backend dari kunci snapshot quiz.",
    )
    st.write(f"Benar **{result['correct_count']}** dari **{result['question_count']}** soal.")
    question_map = {
        int(item["id"]): item for item in (quiz or {}).get("questions", [])
    }
    for number, review in enumerate(result.get("review", []), start=1):
        question = question_map.get(int(review["question_id"]), {})
        option_map = {int(item["id"]): item["text"] for item in question.get("options", [])}
        verdict = "Benar" if review["is_correct"] else "Belum tepat"
        with st.expander(f"Soal {number} · {verdict}", expanded=not review["is_correct"]):
            if question.get("question"):
                st.write(question["question"])
            st.write(
                "Jawaban Anda:",
                option_map.get(int(review["selected_option_id"]), "Opsi tersimpan"),
            )
            st.write(
                "Kunci:", option_map.get(int(review["correct_option_id"]), "Opsi tersimpan")
            )
            st.write(review["explanation"])
            for source in review.get("sources", []):
                page_label = (
                    f", halaman {source['page_number']}" if source.get("page_number") else ""
                )
                st.caption(f"{source['reference_id']} · {source['source_name']}{page_label}")
                st.code(source["excerpt"], language=None, wrap_lines=True)


def _remember_quiz_answer(widget_key: str) -> None:
    drafts = dict(st.session_state.get("quiz_answer_drafts", {}))
    drafts[widget_key] = st.session_state.get(widget_key)
    st.session_state["quiz_answer_drafts"] = drafts


def _render_quiz_questions(client: PyMentorApiClient, quiz: dict[str, Any]) -> None:
    st.subheader(f"Quiz #{quiz['id']} · {quiz['topic']}")
    st.caption("Kunci dan pembahasan tidak tersedia sebelum seluruh jawaban dikirim.")
    for number, question in enumerate(quiz["questions"], start=1):
        st.write(f"**{number}. {question['question']}**")
        option_ids = [int(option["id"]) for option in question["options"]]
        labels = {int(option["id"]): option["text"] for option in question["options"]}
        widget_key = answer_widget_key(int(quiz["id"]), int(question["id"]))
        drafts = st.session_state.get("quiz_answer_drafts", {})
        if widget_key not in st.session_state and isinstance(drafts, dict):
            st.session_state[widget_key] = drafts.get(widget_key)
        st.radio(
            f"Jawaban soal {number}",
            option_ids,
            index=None,
            format_func=lambda value, option_labels=labels: option_labels[value],
            key=widget_key,
            on_change=_remember_quiz_answer,
            args=(widget_key,),
            label_visibility="collapsed",
        )
    with st.form(f"quiz_submit_{quiz['id']}"):
        pending = st.session_state.get("pending_quiz_submission")
        button_label = "Kirim ulang jawaban yang sama" if pending is not None else "Kirim jawaban"
        st.caption("Pengiriman hanya terjadi setelah tombol berikut ditekan.")
        submit = st.form_submit_button(button_label, type="primary")
    if submit:
        try:
            payload = build_answer_payload(quiz, st.session_state)
        except ValueError as exc:
            st.warning(str(exc))
            return
        submission = prepare_submission(
            st.session_state, quiz_id=int(quiz["id"]), payload=payload
        )
        try:
            with st.spinner("Mengirim jawaban untuk dinilai backend…"):
                result = client.submit_attempt(
                    int(quiz["id"]),
                    idempotency_key=submission.idempotency_key,
                    payload=submission.payload,
                )
            finish_submission(st.session_state, result)
            st.success("Jawaban tersimpan dan dinilai.")
        except ApiClientError as exc:
            if not exc.outcome_uncertain:
                abandon_pending_submission(st.session_state)
            _show_action_error(exc)


def render_quiz(client: PyMentorApiClient) -> None:
    st.header("Kuis")
    topics_page = _api_read("Memuat topik…", lambda: client.list_topics(limit=100, offset=0))
    documents_page = _api_read(
        "Memuat dokumen siap…", lambda: client.list_documents(limit=100, offset=0)
    )
    quizzes_page = _api_read("Memuat quiz tersimpan…", lambda: client.list_quizzes(limit=100))
    attempts_page = _api_read(
        "Memuat hasil tersimpan…", lambda: client.list_attempts(limit=100)
    )
    if topics_page is None or documents_page is None:
        return
    topics = list(topics_page.get("items", []))
    ready = _ready_documents(documents_page.get("items", []))

    with st.expander("Buat topik baru"):
        with st.form("create_topic"):
            topic_id = st.text_input("ID stabil", placeholder="python-functions")
            display_name = st.text_input("Nama topik", placeholder="Fungsi Python")
            description = st.text_area("Deskripsi singkat (opsional)", max_chars=500)
            create_topic_clicked = st.form_submit_button("Simpan topik")
        if create_topic_clicked:
            try:
                result = client.create_topic(
                    topic_id=topic_id,
                    display_name=display_name,
                    description=description or None,
                )
                topics.append(result)
                st.success(f"Topik {result['display_name']} berhasil dibuat.")
            except ApiClientError as exc:
                _show_action_error(exc)

    if not topics:
        st.info("Buat topik sebelum menghasilkan quiz.")
    else:
        topic_labels = {item["id"]: item["display_name"] for item in topics}
        selected_topic = st.selectbox(
            "Topik quiz",
            list(topic_labels),
            format_func=lambda value, labels=topic_labels: labels[value],
        )
        scope = _document_scope_controls(ready, key_prefix="quiz")
        with st.form("generate_quiz"):
            topic_prompt = st.text_input(
                "Fokus quiz",
                value=topic_labels[selected_topic],
                max_chars=500,
                help="Instruksi topik untuk generation; topik stabil tetap dipilih di atas.",
            )
            question_count = st.number_input(
                "Jumlah soal", min_value=1, max_value=5, value=3, step=1
            )
            generate = st.form_submit_button("Buat quiz", type="primary")
        if generate:
            try:
                with st.spinner("Mencari sumber dan membuat quiz…"):
                    quiz = client.create_quiz(
                        topic_id=selected_topic,
                        topic=topic_prompt,
                        document_ids=scope,
                        question_count=int(question_count),
                    )
                st.session_state["current_quiz"] = quiz
                st.session_state.pop("quiz_result", None)
                abandon_pending_submission(st.session_state)
                st.success(f"Quiz #{quiz['id']} berhasil dibuat.")
            except ApiClientError as exc:
                _show_action_error(exc)

    saved_quizzes = [] if quizzes_page is None else quizzes_page.get("items", [])
    if saved_quizzes:
        labels = {
            int(item["id"]): f"#{item['id']} · {item['topic']} ({item['question_count']} soal)"
            for item in saved_quizzes
        }
        saved_id = st.selectbox(
            "Buka quiz tersimpan",
            list(labels),
            format_func=lambda value, quiz_labels=labels: quiz_labels[value],
        )
        if st.button("Buka quiz", key="open_saved_quiz"):
            quiz = _api_read("Memuat quiz…", lambda: client.get_quiz(int(saved_id)))
            if quiz is not None:
                st.session_state["current_quiz"] = quiz
                st.session_state.pop("quiz_result", None)
                abandon_pending_submission(st.session_state)

    saved_attempts = [] if attempts_page is None else attempts_page.get("items", [])
    if saved_attempts:
        labels = {
            int(item["id"]): (
                f"Attempt #{item['id']} · quiz #{item['quiz_id']} · {item['percentage']:.2f}%"
            )
            for item in saved_attempts
        }
        attempt_id = st.selectbox(
            "Buka hasil tersimpan",
            list(labels),
            format_func=lambda value, attempt_labels=labels: attempt_labels[value],
        )
        if st.button("Buka hasil", key="open_saved_attempt"):
            selected = next(item for item in saved_attempts if int(item["id"]) == attempt_id)
            result = _api_read("Memuat hasil…", lambda: client.get_attempt(int(attempt_id)))
            quiz = _api_read(
                "Memuat snapshot quiz…", lambda: client.get_quiz(int(selected["quiz_id"]))
            )
            if result is not None and quiz is not None:
                st.session_state["current_quiz"] = quiz
                st.session_state["quiz_result"] = result
                abandon_pending_submission(st.session_state)

    current_quiz = st.session_state.get("current_quiz")
    if isinstance(current_quiz, dict):
        _render_quiz_questions(client, current_quiz)
    result = st.session_state.get("quiz_result")
    if isinstance(result, dict):
        _render_attempt_result(result, current_quiz if isinstance(current_quiz, dict) else None)
        if st.button("Mulai percobaan baru", type="primary") and isinstance(current_quiz, dict):
            quiz_id = int(current_quiz["id"])
            drafts = dict(st.session_state.get("quiz_answer_drafts", {}))
            for question in current_quiz.get("questions", []):
                widget_key = answer_widget_key(quiz_id, int(question["id"]))
                st.session_state.pop(widget_key, None)
                drafts.pop(widget_key, None)
            st.session_state["quiz_answer_drafts"] = drafts
            st.session_state.pop("quiz_result", None)
            abandon_pending_submission(st.session_state)
            st.rerun()


def render_progress(client: PyMentorApiClient) -> None:
    st.header("Progres")
    st.caption(
        "Skor adalah performa latihan dari attempt terbaru per quiz, bukan ukuran mastery "
        "yang tervalidasi secara ilmiah."
    )
    topics_page = _api_read("Memuat topik…", lambda: client.list_topics(limit=100, offset=0))
    if topics_page is None:
        return
    topics = topics_page.get("items", [])
    if not topics:
        st.info("Belum ada topik. Buat topik dari halaman Kuis.")
    for topic in topics:
        progress = _api_read(
            f"Menghitung progres {topic['display_name']}…",
            lambda topic_id=topic["id"]: client.get_topic_progress(topic_id),
        )
        if progress is None:
            continue
        with st.expander(topic["display_name"], expanded=True):
            score = "Belum ada" if progress["score"] is None else f"{progress['score']:.2f}%"
            st.metric("Skor latihan", score)
            st.write(
                f"Bukti: **{progress['counted_questions']} soal** dari "
                f"**{progress['counted_quizzes']} quiz**"
            )
            st.write(f"Rekomendasi: **{progress['recommendation']}**")
            st.info(progress["message"])

    unassigned_page = _api_read(
        "Memeriksa quiz tanpa topik…", lambda: client.list_quizzes(limit=100, unassigned=True)
    )
    unassigned = [] if unassigned_page is None else unassigned_page.get("items", [])
    st.subheader("Quiz legacy tanpa topik")
    if not unassigned:
        st.success("Tidak ada quiz yang menunggu assignment.")
        return
    st.warning(
        "Assignment memindahkan seluruh kontribusi attempt quiz—termasuk histori—ke topik "
        "yang dipilih. Snapshot soal tidak berubah. Periksa topiknya sebelum menyimpan."
    )
    quiz_labels = {int(item["id"]): f"#{item['id']} · {item['topic']}" for item in unassigned}
    topic_labels = {item["id"]: item["display_name"] for item in topics}
    if not topic_labels:
        st.info("Buat topik dari halaman Kuis sebelum melakukan assignment.")
        return
    with st.form("assign_topic"):
        quiz_id = st.selectbox(
            "Quiz legacy",
            list(quiz_labels),
            format_func=lambda value, labels=quiz_labels: labels[value],
        )
        topic_id = st.selectbox(
            "Topik tujuan",
            list(topic_labels),
            format_func=lambda value, labels=topic_labels: labels[value],
        )
        assign = st.form_submit_button("Tetapkan topik", type="primary")
    if assign:
        try:
            result = client.assign_quiz_topic(int(quiz_id), topic_id)
            st.success(f"Quiz #{result['quiz_id']} sekarang berada di topik {topic_id}.")
        except ApiClientError as exc:
            _show_action_error(exc)


def main() -> None:
    st.set_page_config(
        page_title="PyMentor AI",
        page_icon="🐍",
        layout="centered",
        initial_sidebar_state="expanded",
    )
    st.title("PyMentor AI")
    st.caption("Tutor Python berbasis materi Anda")
    try:
        client = get_api_client()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    page = st.sidebar.radio("Navigasi", PAGES, key="navigation")
    st.sidebar.caption("Draft tersimpan selama sesi browser ini aktif.")
    if page == PAGE_MATERIAL:
        render_material(client)
    elif page == PAGE_TUTOR:
        render_tutor(client)
    elif page == PAGE_QUIZ:
        render_quiz(client)
    else:
        render_progress(client)


if __name__ == "__main__":
    main()
