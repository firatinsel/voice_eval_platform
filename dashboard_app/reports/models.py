from django.db import models

class EvaluationRecord(models.Model):
    id = models.UUIDField(primary_key=True)
    call_id = models.CharField(max_length=128, db_index=True)
    turn_id = models.CharField(max_length=128, db_index=True)
    bot_id = models.CharField(max_length=128, db_index=True)
    stt_provider = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    tts_provider = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    action = models.CharField(max_length=32, db_index=True)
    overall_score = models.FloatField()
    audio_processing_status = models.CharField(max_length=32, db_index=True)
    audio_score = models.FloatField(null=True, blank=True)
    stt_score = models.FloatField(null=True, blank=True)
    tts_score = models.FloatField(null=True, blank=True)
    stt_latency_ms = models.FloatField(null=True, blank=True)
    tts_latency_ms = models.FloatField(null=True, blank=True)
    diagnostics = models.JSONField(default=list)
    deep_audio_metrics = models.JSONField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "evaluations"
        managed = False
        verbose_name = "Voice Turn Evaluation"
        verbose_name_plural = "Voice Turn Evaluations"
        ordering = ["-created_at"]