import asyncio
import time
import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict
from datetime import datetime

import fitz  # PyMuPDF

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

import utils.agent_logic as agent_logic
import utils.database as db

from . import cache

chat = Blueprint("chat", __name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

MAX_FILES = 20  # Tăng từ 12 lên 20 cho bulk CV processing
MAX_FILE_SIZE_MB = 10
MAX_WORKERS = 6  # Tăng workers cho xử lý nhanh hơn


# =============================================================================
# CACHING
# =============================================================================


@cache.memoize(timeout=300)
def get_cached_chat_list(user_id):
    print(f"CACHE MISS: Đang tải chat list cho user {user_id}")
    return db.load_chat_list(user_id)


@cache.memoize(timeout=300)
def get_cached_messages(chat_id):
    print(f"CACHE MISS: Đang tải tin nhắn cho chat {chat_id}")
    return db.load_messages(chat_id)


# =============================================================================
# ENHANCED FILE PROCESSING
# =============================================================================


def _extract_text_from_single_pdf(file_storage) -> Tuple[str, str, str, Dict]:
    """
    Trích xuất text từ 1 file PDF với metadata

    Returns:
        Tuple[filename, extracted_text, error_message, metadata]
    """
    filename = file_storage.filename

    try:
        # Validate file size
        file_storage.seek(0, 2)
        file_size = file_storage.tell()
        file_storage.seek(0)

        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            return (
                filename,
                "",
                f"File quá lớn (>{MAX_FILE_SIZE_MB}MB)",
                {"error": True},
            )

        # Read and process PDF
        file_bytes = file_storage.read()
        pdf_document = fitz.open(stream=file_bytes, filetype="pdf")

        extracted_text = []
        page_count = len(pdf_document)

        for page_num in range(page_count):
            page = pdf_document.load_page(page_num)
            extracted_text.append(page.get_text("text"))

        pdf_document.close()

        full_text = "\n".join(extracted_text).strip()

        if not full_text:
            return (
                filename,
                "",
                "PDF trống hoặc không trích xuất được text",
                {"error": True},
            )

        # Enhanced metadata
        metadata = {
            "page_count": page_count,
            "word_count": len(full_text.split()),
            "char_count": len(full_text),
            "file_size_kb": round(file_size / 1024, 2),
            "processed_at": datetime.now().isoformat(),
        }

        return (filename, full_text, None, metadata)

    except Exception as e:
        return (filename, "", f"Lỗi: {str(e)}", {"error": True})


def _classify_document_type(text: str) -> str:
    """
    Phân loại document là CV hay JD dựa trên nội dung

    Returns:
        "CV" hoặc "JD" hoặc "UNKNOWN"
    """
    text_lower = text.lower()

    # CV indicators
    cv_keywords = [
        "experience",
        "education",
        "skills",
        "profile",
        "summary",
        "work history",
        "employment",
        "projects",
        "achievements",
        "email",
        "phone",
        "linkedin",
        "github",
        "portfolio",
        "kinh nghiệm",
        "học vấn",
        "kỹ năng",
        "hồ sơ",
    ]

    # JD indicators
    jd_keywords = [
        "requirements",
        "responsibilities",
        "qualifications",
        "we are looking for",
        "job description",
        "role",
        "required skills",
        "preferred skills",
        "about the role",
        "yêu cầu",
        "trách nhiệm",
        "mô tả công việc",
    ]

    cv_score = sum(1 for keyword in cv_keywords if keyword in text_lower)
    jd_score = sum(1 for keyword in jd_keywords if keyword in text_lower)

    if cv_score > jd_score and cv_score >= 3:
        return "CV"
    elif jd_score > cv_score and jd_score >= 3:
        return "JD"
    else:
        return "UNKNOWN"


def _process_uploaded_files(files) -> dict:
    """
    Xử lý nhiều files PDF song song với phân loại thông minh

    Returns:
        dict với:
        - cv_files: List[dict] - CVs đã xử lý
        - jd_files: List[dict] - JDs đã xử lý
        - unknown_files: List[dict] - Files không xác định được
        - errors: List[dict] - Lỗi
        - stats: Dict - Thống kê
    """
    if not files:
        return {
            "cv_files": [],
            "jd_files": [],
            "unknown_files": [],
            "errors": [],
            "stats": {
                "total": 0,
                "successful": 0,
                "cv_count": 0,
                "jd_count": 0,
                "unknown_count": 0,
                "failed": 0,
            },
        }

    # Validate số lượng files
    if len(files) > MAX_FILES:
        return {
            "cv_files": [],
            "jd_files": [],
            "unknown_files": [],
            "errors": [
                {
                    "file_name": "System",
                    "error": f"Quá nhiều files. Tối đa {MAX_FILES} files.",
                }
            ],
            "stats": {"total": len(files), "successful": 0, "failed": len(files)},
        }

    cv_files = []
    jd_files = []
    unknown_files = []
    errors = []

    print(f"📁 Processing {len(files)} file(s) với phân loại tự động...")

    # Xử lý song song
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_file = {
            executor.submit(_extract_text_from_single_pdf, file): file.filename
            for file in files
            if file and file.filename.lower().endswith(".pdf")
        }

        for future in as_completed(future_to_file):
            filename, text, error, metadata = future.result()

            if error:
                errors.append({"file_name": filename, "error": error})
                print(f"❌ {filename}: {error}")
            else:
                # Classify document
                doc_type = _classify_document_type(text)

                file_info = {
                    "file_name": filename,
                    "content": text,
                    "doc_type": doc_type,
                    "metadata": metadata,
                }

                if doc_type == "CV":
                    cv_files.append(file_info)
                    print(
                        f"✅ {filename}: CV detected ({metadata['word_count']} words)"
                    )
                elif doc_type == "JD":
                    jd_files.append(file_info)
                    print(
                        f"✅ {filename}: JD detected ({metadata['word_count']} words)"
                    )
                else:
                    unknown_files.append(file_info)
                    print(
                        f"⚠️ {filename}: Type unknown ({metadata['word_count']} words)"
                    )

    stats = {
        "total": len(files),
        "successful": len(cv_files) + len(jd_files) + len(unknown_files),
        "cv_count": len(cv_files),
        "jd_count": len(jd_files),
        "unknown_count": len(unknown_files),
        "failed": len(errors),
    }

    return {
        "cv_files": cv_files,
        "jd_files": jd_files,
        "unknown_files": unknown_files,
        "errors": errors,
        "stats": stats,
    }


def _format_files_for_prompt(processing_result: dict) -> str:
    """
    Format extracted files thành context cho AI với phân loại rõ ràng
    """
    if processing_result["stats"]["successful"] == 0:
        return ""

    formatted_sections = []
    stats = processing_result["stats"]

    # Header with summary
    summary = f"""
=== 📊 FILE PROCESSING SUMMARY ===
Total Files: {stats['total']}
✅ Successfully Processed: {stats['successful']}
   • CVs: {stats['cv_count']}
   • Job Descriptions: {stats['jd_count']}
   • Unknown: {stats['unknown_count']}
❌ Failed: {stats['failed']}
===================================

"""
    formatted_sections.append(summary)

    # Format CVs
    if processing_result["cv_files"]:
        cv_section = "=== 📄 CANDIDATE CVs ===\n\n"
        for idx, cv in enumerate(processing_result["cv_files"], 1):
            cv_section += f"""
[CV #{idx}: {cv['file_name']}]
Metadata: {cv['metadata']['word_count']} words, {cv['metadata']['page_count']} pages
---
{cv['content']}
---
[END CV #{idx}]

"""
        formatted_sections.append(cv_section)

    # Format JDs
    if processing_result["jd_files"]:
        jd_section = "=== 📋 JOB DESCRIPTIONS ===\n\n"
        for idx, jd in enumerate(processing_result["jd_files"], 1):
            jd_section += f"""
[JD #{idx}: {jd['file_name']}]
Metadata: {jd['metadata']['word_count']} words, {jd['metadata']['page_count']} pages
---
{jd['content']}
---
[END JD #{idx}]

"""
        formatted_sections.append(jd_section)

    # Format unknown files
    if processing_result["unknown_files"]:
        unknown_section = "=== ❓ UNCLASSIFIED DOCUMENTS ===\n\n"
        for idx, doc in enumerate(processing_result["unknown_files"], 1):
            unknown_section += f"""
[DOCUMENT #{idx}: {doc['file_name']}]
{doc['content']}
[END DOCUMENT #{idx}]

"""
        formatted_sections.append(unknown_section)

    # Add errors
    if processing_result["errors"]:
        error_section = "\n=== ⚠️ PROCESSING ERRORS ===\n"
        for error_item in processing_result["errors"]:
            error_section += f"❌ {error_item['file_name']}: {error_item['error']}\n"
        error_section += "============================\n"
        formatted_sections.append(error_section)

    return "\n".join(formatted_sections)


# =============================================================================
# PROACTIVE FEATURES
# =============================================================================


def _get_pending_reminders(user_id: int) -> dict:
    """
    Lấy các reminder và actions đang chờ xử lý
    """
    try:
        # Gọi agent's get_pending_actions tool
        pending = asyncio.run(
            agent_logic.get_pending_actions(user_id=user_id, days_ahead=7)
        )
        return pending
    except Exception as e:
        print(f"⚠️ Không thể lấy pending reminders: {e}")
        return {"success": False, "overdue": [], "pending": []}


def _format_reminders_for_ui(reminders: dict) -> str:
    """
    Format reminders thành HTML/Markdown cho UI
    """
    if not reminders.get("success"):
        return ""

    overdue = reminders.get("overdue", [])
    pending = reminders.get("pending", [])

    if not overdue and not pending:
        return ""

    output = []

    if overdue:
        output.append("⏰ **ACTIONS OVERDUE:**\n")
        for action in overdue[:5]:  # Top 5
            output.append(
                f"🔴 **{action['candidate']}**: {action['action']} "
                f"(overdue {action['days_overdue']} days)\n"
            )

    if pending:
        output.append("\n📅 **UPCOMING ACTIONS:**\n")
        for action in pending[:5]:  # Top 5
            priority_emoji = {
                "Critical": "🔥",
                "High": "⚠️",
                "Medium": "📌",
                "Low": "ℹ️",
            }.get(action.get("priority", "Medium"), "📌")

            output.append(
                f"{priority_emoji} **{action['candidate']}**: {action['action']} "
                f"(due in {action['days_until_due']} days)\n"
            )

    return "\n".join(output)


# =============================================================================
# ROUTES CHO GIAO DIỆN
# =============================================================================


@chat.route("/")
@login_required
def index():
    return render_template("chat.html")


# =============================================================================
# API ENDPOINTS
# =============================================================================


@chat.route("/api/chats", methods=["GET"])
@login_required
def api_get_chats():
    """Lấy danh sách lịch sử chat"""
    chat_list = get_cached_chat_list(current_user.id)
    return jsonify(chat_list)


@chat.route("/api/chats", methods=["POST"])
@login_required
def api_new_chat():
    """Tạo một chat mới"""
    new_chat_id = db.create_conversation(current_user.id)
    cache.delete_memoized(get_cached_chat_list, current_user.id)
    return jsonify({"id": new_chat_id, "title": "New Recruitment Chat"})


@chat.route("/api/chat/<int:chat_id>/messages", methods=["GET"])
@login_required
def api_get_messages(chat_id):
    """Lấy tin nhắn của một chat cụ thể"""
    messages = get_cached_messages(chat_id)
    return jsonify(messages)


@chat.route("/api/reminders", methods=["GET"])
@login_required
def api_get_reminders():
    """
    Lấy các reminders và pending actions cho user
    """
    try:
        reminders = _get_pending_reminders(current_user.id)
        formatted = _format_reminders_for_ui(reminders)

        return jsonify(
            {
                "success": True,
                "reminders": reminders,
                "formatted_html": formatted,
                "count": reminders.get("summary", {}).get("total", 0),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@chat.route("/api/chat/<int:chat_id>", methods=["POST"])
@login_required
def api_send_message(chat_id):
    """
    Gửi một tin nhắn mới với hỗ trợ upload nhiều files
    ENHANCED: Với auto-classification và intelligent routing
    """

    # Get data from request
    prompt = request.form.get("prompt", "").strip()
    uploaded_files = request.files.getlist("files")

    # Validation
    if not prompt and not uploaded_files:
        return jsonify({"error": "Không có prompt hoặc files"}), 400

    # Process uploaded files với classification
    processing_result = _process_uploaded_files(uploaded_files)

    # Check if all files failed
    if uploaded_files and processing_result["stats"]["successful"] == 0:
        error_msg = "Không thể xử lý files. "
        if processing_result["errors"]:
            error_msg += processing_result["errors"][0]["error"]
        return jsonify({"error": error_msg}), 400

    # Format file context for AI
    file_context = _format_files_for_prompt(processing_result)

    # Create enhanced prompt
    full_prompt_parts = []

    # Add file context if exists
    if file_context:
        full_prompt_parts.append(file_context)

    # Add intelligent routing hint based on files
    stats = processing_result["stats"]
    if stats["cv_count"] > 0 and stats["jd_count"] > 0:
        full_prompt_parts.append(
            "\n🎯 **SMART ROUTING:** CVs and JD detected → Perform automatic matching analysis\n"
        )
    elif stats["cv_count"] > 5:
        full_prompt_parts.append(
            "\n🎯 **SMART ROUTING:** Multiple CVs detected → Batch processing mode\n"
        )

    # Add user prompt
    if prompt:
        full_prompt_parts.append(
            f"\n=== USER REQUEST ===\n{prompt}\n==================="
        )
    else:
        # Default prompt if only files uploaded
        if stats["cv_count"] > 0:
            full_prompt_parts.append(
                f"\n=== USER REQUEST ===\n"
                f"Tôi đã upload {stats['cv_count']} CV(s). "
                f"Hãy phân tích và tổng hợp thông tin ứng viên một cách chi tiết.\n"
                f"==================="
            )

    full_prompt = "\n".join(full_prompt_parts).strip()

    # Save user message với summary
    if stats["successful"] > 0:
        display_message = prompt if prompt else f"📎 Uploaded {stats['cv_count']} CV(s)"
        if stats["jd_count"] > 0:
            display_message += f", {stats['jd_count']} JD(s)"
    else:
        display_message = prompt

    db.save_message(chat_id, "user", display_message)
    cache.delete_memoized(get_cached_messages, chat_id)

    # Get chat history
    chat_history = get_cached_messages(chat_id)

    # Call Enhanced Agent
    try:
        start_time = time.time()

        # Metadata for agent
        agent_metadata = {
            "total_files": stats["total"],
            "cv_count": stats["cv_count"],
            "jd_count": stats["jd_count"],
            "unknown_count": stats["unknown_count"],
            "successful_files": stats["successful"],
            "failed_files": stats["failed"],
            "file_names": {
                "cvs": [f["file_name"] for f in processing_result["cv_files"]],
                "jds": [f["file_name"] for f in processing_result["jd_files"]],
                "unknown": [f["file_name"] for f in processing_result["unknown_files"]],
            },
        }

        final_output = asyncio.run(
            agent_logic.run_agent_simulation(
                prompt=full_prompt,
                user_id=int(current_user.id),
                chat_history=chat_history,
                metadata=agent_metadata,
            )
        )

        end_time = time.time()

        # Format response với file processing summary
        response_parts = [final_output]

        # Add processing summary footer
        if uploaded_files:
            footer_parts = ["\n\n---"]

            if stats["cv_count"] > 0:
                footer_parts.append(f"📄 **Processed:** {stats['cv_count']} CV(s)")
            if stats["jd_count"] > 0:
                footer_parts.append(f"📋 **Processed:** {stats['jd_count']} JD(s)")
            if stats["failed"] > 0:
                footer_parts.append(f"⚠️ **Failed:** {stats['failed']} file(s)")

            footer_parts.append(f"⏱️ *Completed in {end_time - start_time:.2f}s*")

            response_parts.append("\n".join(footer_parts))

        response_content = "\n".join(response_parts)

        # Save assistant message
        db.save_message(chat_id, "assistant", response_content)
        cache.delete_memoized(get_cached_messages, chat_id)

        # Update title for first message
        if len(chat_history) == 3:
            if stats["cv_count"] > 0:
                title = f"{stats['cv_count']} CVs Analysis"
            elif prompt:
                title = prompt[:40] + "..." if len(prompt) > 40 else prompt
            else:
                title = "New Recruitment Task"

            db.update_conversation_title(chat_id, title)
            cache.delete_memoized(get_cached_chat_list, current_user.id)

        return jsonify(
            {
                "role": "assistant",
                "content": response_content,
                "metadata": {
                    "processing_time": round(end_time - start_time, 2),
                    "files_processed": stats,
                },
            }
        )

    except Exception as e:
        error_message = f"❌ Lỗi xảy ra: {str(e)}"
        db.save_message(chat_id, "assistant", error_message)
        cache.delete_memoized(get_cached_messages, chat_id)
        return jsonify({"error": error_message}), 500


@chat.route("/api/chat/<int:chat_id>", methods=["DELETE"])
@login_required
def api_delete_chat(chat_id):
    """Xóa một chat"""
    db.delete_conversation(chat_id)
    cache.delete_memoized(get_cached_chat_list, current_user.id)
    cache.delete_memoized(get_cached_messages, chat_id)
    return jsonify({"success": True})


@chat.route("/api/chat/<int:chat_id>/title", methods=["PUT"])
@login_required
def api_update_title(chat_id):
    """Cập nhật tiêu đề chat"""
    data = request.json
    new_title = data.get("title")
    if new_title:
        db.update_conversation_title(chat_id, new_title)
        cache.delete_memoized(get_cached_chat_list, current_user.id)
        return jsonify({"success": True})
    return jsonify({"error": "No title provided"}), 400


@chat.route("/api/upload/validate", methods=["POST"])
@login_required
def api_validate_upload():
    """
    Validate files trước khi upload
    """
    files = request.files.getlist("files")

    validation_results = {
        "valid": True,
        "total_files": len(files),
        "errors": [],
        "warnings": [],
    }

    # Check số lượng
    if len(files) > MAX_FILES:
        validation_results["valid"] = False
        validation_results["errors"].append(
            f"Quá nhiều files. Tối đa {MAX_FILES} files."
        )
        return jsonify(validation_results), 400

    # Check từng file
    for file in files:
        # Check file type
        if not file.filename.lower().endswith(".pdf"):
            validation_results["valid"] = False
            validation_results["errors"].append(
                f"{file.filename}: Chỉ chấp nhận PDF files"
            )

        # Check file size
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)

        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            validation_results["valid"] = False
            validation_results["errors"].append(
                f"{file.filename}: File quá lớn (max {MAX_FILE_SIZE_MB}MB)"
            )
        elif file_size == 0:
            validation_results["warnings"].append(f"{file.filename}: File trống")

    return jsonify(validation_results)


@chat.route("/api/quick-actions", methods=["GET"])
@login_required
def api_get_quick_actions():
    """
    Lấy danh sách quick actions dựa trên context hiện tại
    """
    try:
        # Get memory stats
        stats_result = agent_logic.get_memory_stats(user_id=current_user.id)
        stats = stats_result.get("stats", {}) if stats_result.get("success") else {}

        quick_actions = []

        # Action suggestions based on current state
        candidate_count = stats.get("by_type", {}).get("candidate", 0)
        jd_count = stats.get("by_type", {}).get("jd", 0)

        if candidate_count > 0 and jd_count > 0:
            quick_actions.append(
                {
                    "id": "match_candidates",
                    "label": f"📊 Match {candidate_count} Candidates to JD",
                    "prompt": "Hãy so sánh và xếp hạng các ứng viên hiện có với job description",
                }
            )

        if candidate_count > 5:
            quick_actions.append(
                {
                    "id": "generate_report",
                    "label": f"📈 Generate Pipeline Report",
                    "prompt": "Tạo báo cáo tổng quan về pipeline tuyển dụng hiện tại",
                }
            )

        if candidate_count > 0:
            quick_actions.append(
                {
                    "id": "find_similar",
                    "label": "🔍 Find Similar Candidates",
                    "prompt": "Tìm thêm ứng viên tương tự với các ứng viên hiện tại",
                }
            )

            quick_actions.append(
                {
                    "id": "generate_outreach",
                    "label": "📧 Generate Outreach Messages",
                    "prompt": "Tạo tin nhắn outreach cho top 3 ứng viên",
                }
            )

        # Always available actions
        quick_actions.extend(
            [
                {
                    "id": "search_candidates",
                    "label": "🎯 Search New Candidates",
                    "prompt": "Tôi muốn tìm ứng viên cho vị trí...",
                },
                {
                    "id": "upload_cvs",
                    "label": "📤 Upload CVs for Analysis",
                    "action": "upload",
                },
            ]
        )

        return jsonify(
            {
                "success": True,
                "actions": quick_actions,
                "context": {"candidate_count": candidate_count, "jd_count": jd_count},
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e), "actions": []})


@chat.route("/api/analytics", methods=["GET"])
@login_required
def api_get_analytics():
    """
    Lấy analytics data cho dashboard
    """
    try:
        # Get memory stats
        stats_result = agent_logic.get_memory_stats(user_id=current_user.id)

        if not stats_result.get("success"):
            return jsonify({"success": False, "error": "Could not fetch analytics"})

        stats = stats_result.get("stats", {})

        # Get pending actions
        pending_result = asyncio.run(
            agent_logic.get_pending_actions(user_id=current_user.id, days_ahead=30)
        )

        analytics = {
            "total_candidates": stats.get("by_type", {}).get("candidate", 0),
            "total_jds": stats.get("by_type", {}).get("jd", 0),
            "total_workflows": stats.get("by_type", {}).get("workflow", 0),
            "pending_actions": (
                pending_result.get("summary", {}).get("total", 0)
                if pending_result.get("success")
                else 0
            ),
            "overdue_actions": (
                pending_result.get("summary", {}).get("overdue_count", 0)
                if pending_result.get("success")
                else 0
            ),
            "last_updated": stats.get("last_updated"),
        }

        return jsonify({"success": True, "analytics": analytics})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# =============================================================================
# HELPER ROUTES
# =============================================================================


@chat.route("/api/health", methods=["GET"])
def api_health_check():
    """Health check endpoint"""
    return jsonify(
        {
            "status": "healthy",
            "service": "talent_acquisition_chat",
            "timestamp": datetime.now().isoformat(),
            "features": {
                "file_upload": True,
                "batch_processing": True,
                "auto_classification": True,
                "reminders": True,
                "analytics": True,
            },
        }
    )


if __name__ == "__main__":
    print("=" * 70)
    print("🚀 ENHANCED TALENT ACQUISITION CHAT SYSTEM")
    print("=" * 70)
    print("\n✨ Features:")
    print("   • Bulk CV processing (up to 20 files)")
    print("   • Auto document classification (CV/JD)")
    print("   • Proactive reminders & notifications")
    print("   • Quick actions & shortcuts")
    print("   • Analytics dashboard")
    print("   • Smart routing based on context")
    print("\n🎯 Ready to supercharge your recruitment!")
    print("=" * 70)
