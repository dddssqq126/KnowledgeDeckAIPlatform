from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        return None
    if user.password != password:
        return None
    return user


async def get_or_create_user(session: AsyncSession, username: str) -> User:
    """Resolve a username to a User, provisioning one on first sight.

    Backs the passwordless external-user login. The created row has an empty
    password, which can never satisfy /auth/login (its request rejects empty
    passwords), so external users stay password-less.
    """
    user = await session.scalar(select(User).where(User.username == username))
    if user is not None:
        return user
    user = User(username=username, password="")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
