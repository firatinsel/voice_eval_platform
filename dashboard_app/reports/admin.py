from django.contrib import admin
from django.utils.html import format_html
from .models import EvaluationRecord

@admin.register(EvaluationRecord)
class EvaluationRecordAdmin(admin.ModelAdmin):
    list_display = (
        "call_id",
        "turn_id",
        "bot_id",
        "action_badge",
        "colored_score",
        "audio_processing_status",
        "created_at",
    )
    list_filter = (
        "action",
        "bot_id",
        "stt_provider",
        "tts_provider",
        "audio_processing_status",
    )
    search_fields = ("call_id", "turn_id", "bot_id")
    readonly_fields = [f.name for f in EvaluationRecord._meta.fields]

    def action_badge(self, obj):
        colors = {
            "accept": "#28a745",
            "retry_stt": "#ffc107",
            "retry_tts": "#fd7e14",
            "switch_provider": "#dc3545",
            "ask_repeat": "#17a2b8",
            "safe_fallback": "#6c757d",
        }
        color = colors.get(obj.action, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: #fff; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{}</span>',
            color,
            obj.action.upper(),
        )
    action_badge.short_description = "Action"

    def colored_score(self, obj):
        if obj.overall_score is None:
            return "-"
        color = "#28a745" if obj.overall_score >= 0.70 else "#dc3545"
        formatted_score = f"{obj.overall_score:.2f}"
        return format_html('<b style="color: {};">{}</b>', color, formatted_score)
    colored_score.short_description = "Score"