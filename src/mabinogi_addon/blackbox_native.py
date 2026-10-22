"""플랫폼 독립 호출부를 위한 캡처 계약 공개 경로."""
from .system.blackbox_capture import NativeCapture, NativeTransition, Target, target_identity

__all__ = ["NativeCapture", "NativeTransition", "Target", "target_identity"]
