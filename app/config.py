"""App configuration — reads from environment variables (.env)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./jobify.db"

    # JWT
    JWT_SECRET: str = "change-me"
    JWT_EXPIRE_MINUTES: int = 43200  # 30 days
    JWT_ALGORITHM: str = "HS256"

    # --- SMS (Twilio) ---
    # In dev mode the OTP is printed to the server log instead of sending a real SMS,
    # so the full auth flow can be built and tested without any keys.
    SMS_DEV_MODE: bool = True
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""   # your Twilio phone number, e.g. +1234567890

    # OTP
    OTP_EXPIRE_MINUTES: int = 10
    OTP_LENGTH: int = 6

    # Admin phone numbers (comma-separated). Whoever logs in with one of these
    # numbers is granted the admin role. Temporary — will change later.
    ADMIN_PHONES: str = "+919177415501"

    # DEV ONLY: when True, an admin phone takes whatever role is picked on the
    # login screen (candidate/recruiter/admin) instead of always being forced to
    # admin — so a single test number can walk every flow. MUST be False in prod.
    DEV_ROLE_OVERRIDE: bool = True

    @property
    def admin_phone_list(self) -> list[str]:
        return [p.strip() for p in self.ADMIN_PHONES.split(",") if p.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
