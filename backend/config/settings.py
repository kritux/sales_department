from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_key: str = ""
    resend_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""   # E.164, e.g. "+14155238886"
    twilio_phone_number: str = ""      # E.164, outbound voice calls
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel (default)
    audio_base_url: str = ""           # e.g. "https://app.railway.app"; empty → <Say> fallback
    dry_run: bool = True
    log_level: str = "DEBUG"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
