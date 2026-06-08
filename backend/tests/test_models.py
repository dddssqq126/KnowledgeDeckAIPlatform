from app.db.models import ChatInputFile, DeptTime, User


def test_user_table_metadata() -> None:
    assert User.__tablename__ == "users"
    columns = {c.name for c in User.__table__.columns}
    assert columns == {"id", "username", "password", "created_at"}


def test_dept_time_table_metadata() -> None:
    assert DeptTime.__tablename__ == "dept_times"
    columns = {c.name for c in DeptTime.__table__.columns}
    assert columns == {"id", "owner_user_id", "dept", "time"}

    owner_column = DeptTime.__table__.columns["owner_user_id"]
    assert [fk.target_fullname for fk in owner_column.foreign_keys] == ["users.id"]


def test_chat_input_file_table_metadata() -> None:
    assert ChatInputFile.__tablename__ == "chat_input_files"
    columns = {c.name for c in ChatInputFile.__table__.columns}
    assert columns == {
        "id",
        "owner_user_id",
        "session_id",
        "message_id",
        "filename",
        "extension",
        "size_bytes",
        "content_sha256",
        "storage_key",
        "created_at",
    }

    assert [
        fk.target_fullname
        for fk in ChatInputFile.__table__.columns["message_id"].foreign_keys
    ] == ["chat_messages.id"]
