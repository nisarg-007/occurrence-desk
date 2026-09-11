"""Fail visibly when the app owner has not wired persistent storage yet."""

import os


def main():
    from services.api.deps import get_repo
    from services.api.main import app

    if getattr(get_repo(), "is_stub", True):
        raise SystemExit(
            "Integration needed: Nisarg must wire Parva's SqlRepo into get_repo(). "
            "Refusing to call an in-memory demo the M1 stack."
        )
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
