from __future__ import annotations

import base64
import json
import os
import re
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

try:
    import zenoh

    ZENOH_IMPORT_ERROR = ""
except Exception as exc:
    zenoh = None
    ZENOH_IMPORT_ERROR = str(exc)


DEFAULT_BUFFER_SIZE = 500
PACKAGE_DIR = Path(__file__).resolve().parent
MODULE_DIR = PACKAGE_DIR.parent.parent
DEFAULT_ZENOH_CONFIG_PATH = PACKAGE_DIR / "zenoh.json5"
DEFAULT_SERVICE_CONFIG_PATH = PACKAGE_DIR / "zenoh_service.json"


class ZenohServiceClient:
    def __init__(self) -> None:
        self._session_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._session = None
        self._default_config_path: Optional[Path] = None
        self._default_service_config_path: Optional[Path] = None
        self._local_peer_active = False
        self._subscribers: Dict[str, Any] = {}
        self._publishers: Dict[str, Any] = {}
        self._buffers: Dict[str, Deque[Dict[str, Any]]] = {}
        self._message_handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self._last_error = ""

    def initialize(self, auto_subscribe_defaults: bool = True) -> bool:
        try:
            self._ensure_transport_ready()
            if auto_subscribe_defaults:
                return self.subscribe_default_topics()
            return True
        except Exception as exc:
            self._set_last_error(exc)
            return False

    def publish(self, topic: str, payload: Any) -> bool:
        topic = topic.strip()
        if not topic:
            self._set_last_error("topic is required")
            return False
        try:
            data = self._payload_to_bytes(payload)
            self._ensure_transport_ready()
            if self._local_peer_active:
                self._dispatch_local_message(topic, data)
                self._set_last_error("")
                return True

            session = self._get_session()
            with self._state_lock:
                publisher = self._publishers.get(topic)
                if publisher is None:
                    try:
                        publisher = session.declare_publisher(topic)
                        self._publishers[topic] = publisher
                    except Exception:
                        publisher = None
            if publisher is not None and hasattr(publisher, "put"):
                publisher.put(data)
            else:
                session.put(topic, data)
            self._set_last_error("")
            return True
        except Exception as exc:
            self._set_last_error(exc)
            return False

    def subscribe(
        self,
        topic: str,
        buffer_size: Optional[int] = None,
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> bool:
        topic = topic.strip()
        if not topic:
            self._set_last_error("topic is required")
            return False
        try:
            normalized_buffer_size = self._normalize_buffer_size(buffer_size)
            self._ensure_topic_buffer(topic, normalized_buffer_size)
            self._ensure_transport_ready()
            with self._state_lock:
                if topic in self._subscribers:
                    if on_message is not None:
                        self._message_handlers[topic] = on_message
                    self._set_last_error("")
                    return True

                if self._local_peer_active:
                    self._subscribers[topic] = {"mode": "local-peer"}
                    if on_message is not None:
                        self._message_handlers[topic] = on_message
                    self._set_last_error("")
                    return True

                def _callback(sample: Any, subscribed_topic: str = topic) -> None:
                    self._consume_message(
                        subscribed_topic=subscribed_topic,
                        message=self._sample_to_message(sample),
                    )

                session = self._get_session()
                subscriber = session.declare_subscriber(topic, _callback)
                self._subscribers[topic] = subscriber
                if on_message is not None:
                    self._message_handlers[topic] = on_message
            self._set_last_error("")
            return True
        except Exception as exc:
            self._set_last_error(exc)
            return False

    def unsubscribe(self, topic: str) -> bool:
        topic = topic.strip()
        if not topic:
            self._set_last_error("topic is required")
            return False
        with self._state_lock:
            subscriber = self._subscribers.pop(topic, None)
            self._message_handlers.pop(topic, None)
        if subscriber is None:
            self._set_last_error("topic is not subscribed")
            return False
        self._safe_undeclare(subscriber)
        self._set_last_error("")
        return True

    def subscribe_default_topics(self) -> bool:
        try:
            success = True
            for item in self._load_default_subscriptions():
                if not self.subscribe(
                    topic=item["topic"],
                    buffer_size=item["buffer_size"],
                ):
                    success = False
            if success:
                self._set_last_error("")
            return success
        except Exception as exc:
            self._set_last_error(exc)
            return False

    def poll(self, topic: str, limit: int = 50) -> List[Dict[str, Any]]:
        topic = topic.strip()
        if not topic:
            self._set_last_error("topic is required")
            return []
        if limit < 1:
            limit = 1
        if limit > 1000:
            limit = 1000
        with self._state_lock:
            buffer = self._buffers.get(topic)
            if buffer is None:
                self._set_last_error("topic buffer not found")
                return []
            items = list(buffer)[-limit:]
        self._set_last_error("")
        return items

    def recent_messages(self, topic: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self.poll(topic=topic, limit=limit)

    def list_subscriptions(self) -> List[str]:
        with self._state_lock:
            topics = list(self._subscribers.keys())
        self._set_last_error("")
        return topics

    def health(self) -> bool:
        try:
            self._ensure_transport_ready()
            self._set_last_error("")
            return True
        except Exception as exc:
            self._set_last_error(exc)
            return False

    def close(self) -> bool:
        try:
            with self._state_lock:
                subscribers = list(self._subscribers.values())
                publishers = list(self._publishers.values())
                self._subscribers.clear()
                self._publishers.clear()
                self._buffers.clear()
                self._message_handlers.clear()
                self._local_peer_active = False
            for subscriber in subscribers:
                self._safe_undeclare(subscriber)
            for publisher in publishers:
                self._safe_undeclare(publisher)
            with self._session_lock:
                session = self._session
                self._session = None
            if session is not None:
                self._safe_close_session(session)
            self._set_last_error("")
            return True
        except Exception as exc:
            self._set_last_error(exc)
            return False

    def get_last_error(self) -> str:
        return self._last_error

    def get_default_subscriptions(self) -> List[Dict[str, Any]]:
        try:
            subscriptions = self._load_default_subscriptions()
            self._set_last_error("")
            return subscriptions
        except Exception as exc:
            self._set_last_error(exc)
            return []

    def configure_default_paths(
        self,
        config_path: Optional[str | Path] = None,
        service_config_path: Optional[str | Path] = None,
    ) -> None:
        self._default_config_path = Path(config_path).resolve() if config_path else None
        self._default_service_config_path = (
            Path(service_config_path).resolve() if service_config_path else None
        )

    def _set_last_error(self, error: Any) -> None:
        if isinstance(error, Exception):
            self._last_error = str(error)
            return
        self._last_error = str(error or "")

    def _require_zenoh(self) -> None:
        if zenoh is None:
            detail = "zenoh package is not available"
            if ZENOH_IMPORT_ERROR:
                detail = f"{detail}: {ZENOH_IMPORT_ERROR}"
            raise RuntimeError(detail)

    def _get_zenoh_config_candidate(self) -> Path:
        config_path = os.getenv("ZENOH_CONFIG_PATH", "").strip()
        if config_path:
            return Path(config_path)
        if self._default_config_path is not None:
            return self._default_config_path
        return DEFAULT_ZENOH_CONFIG_PATH

    def _get_service_config_candidate(self) -> Path:
        config_path = os.getenv("ZENOH_SERVICE_CONFIG_PATH", "").strip()
        if config_path:
            return Path(config_path)
        if self._default_service_config_path is not None:
            return self._default_service_config_path
        return DEFAULT_SERVICE_CONFIG_PATH

    def _load_service_config(self) -> Dict[str, Any]:
        config_text = os.getenv("ZENOH_SERVICE_CONFIG_JSON", "").strip()
        if config_text:
            try:
                return json.loads(config_text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid ZENOH_SERVICE_CONFIG_JSON: {exc}") from exc

        candidate = self._get_service_config_candidate()
        if not candidate.exists():
            return {}

        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"invalid service config file {candidate}: {exc}"
            ) from exc

    def _load_default_subscriptions(self) -> List[Dict[str, Any]]:
        config = self._load_service_config()
        raw_items = config.get("default_subscriptions", [])
        if raw_items is None:
            return []
        if not isinstance(raw_items, list):
            raise RuntimeError("default_subscriptions must be a list")

        subscriptions: List[Dict[str, Any]] = []
        seen_topics = set()
        for index, item in enumerate(raw_items):
            if isinstance(item, str):
                topic = item.strip()
                buffer_size = DEFAULT_BUFFER_SIZE
            elif isinstance(item, dict):
                topic = str(item.get("topic", "")).strip()
                buffer_size = self._normalize_buffer_size(item.get("buffer_size"))
            else:
                raise RuntimeError(
                    f"default_subscriptions[{index}] must be a string or object"
                )

            if not topic or topic in seen_topics:
                continue
            seen_topics.add(topic)
            subscriptions.append({"topic": topic, "buffer_size": buffer_size})

        return subscriptions

    def _normalize_buffer_size(self, value: Any) -> int:
        if value is None:
            return DEFAULT_BUFFER_SIZE
        try:
            value = int(value)
        except (TypeError, ValueError):
            return DEFAULT_BUFFER_SIZE
        if value < 1:
            return DEFAULT_BUFFER_SIZE
        return value

    def _normalize_bool(self, value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if not text:
            return default
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default

    def _is_local_peer_fallback_enabled(self) -> bool:
        config = self._load_service_config()
        return self._normalize_bool(config.get("local_peer_fallback"), default=True)

    def _ensure_transport_ready(self) -> None:
        if self._local_peer_active:
            return
        try:
            self._get_session()
        except Exception:
            if self._is_local_peer_fallback_enabled():
                with self._state_lock:
                    self._local_peer_active = True
                return
            raise

    def _get_session(self) -> Any:
        self._require_zenoh()
        with self._session_lock:
            if self._session is None:
                config_text = os.getenv("ZENOH_CONFIG_JSON5", "").strip()
                config_obj = None
                candidate = self._get_zenoh_config_candidate()
                if (
                    config_text
                    and hasattr(zenoh, "Config")
                    and hasattr(zenoh.Config, "from_json5")
                ):
                    config_obj = zenoh.Config.from_json5(config_text)
                elif (
                    candidate.exists()
                    and hasattr(zenoh, "Config")
                    and hasattr(zenoh.Config, "from_file")
                ):
                    config_obj = zenoh.Config.from_file(str(candidate))
                elif hasattr(zenoh, "Config"):
                    config_obj = zenoh.Config()
                if config_obj is not None:
                    self._session = zenoh.open(config_obj)
                else:
                    self._session = zenoh.open()
            return self._session

    def _payload_to_bytes(self, payload: Any) -> bytes:
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, (dict, list)):
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if isinstance(payload, (int, float, bool)):
            return str(payload).encode("utf-8")
        if payload is None:
            return b""
        return str(payload).encode("utf-8")

    def _build_message(self, topic: str, raw_bytes: bytes) -> Dict[str, Any]:
        try:
            payload_text = raw_bytes.decode("utf-8")
            is_binary = False
            payload_base64 = None
        except Exception:
            payload_text = ""
            is_binary = True
            payload_base64 = base64.b64encode(raw_bytes).decode("ascii")
        return {
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload_text": payload_text,
            "payload_base64": payload_base64,
            "is_binary": is_binary,
        }

    def _sample_to_message(self, sample: Any) -> Dict[str, Any]:
        payload_obj = getattr(sample, "payload", sample)
        raw_bytes = b""
        if hasattr(payload_obj, "to_bytes"):
            raw_bytes = payload_obj.to_bytes()
        elif isinstance(payload_obj, (bytes, bytearray)):
            raw_bytes = bytes(payload_obj)
        else:
            raw_bytes = str(payload_obj).encode("utf-8")
        key_expr = ""
        if hasattr(sample, "key_expr"):
            key_expr = str(sample.key_expr)
        return self._build_message(topic=key_expr, raw_bytes=raw_bytes)

    def _ensure_topic_buffer(self, topic: str, max_size: int) -> Deque[Dict[str, Any]]:
        with self._state_lock:
            if topic not in self._buffers:
                self._buffers[topic] = deque(maxlen=max_size)
            return self._buffers[topic]

    def _consume_message(self, subscribed_topic: str, message: Dict[str, Any]) -> None:
        handler = None
        with self._state_lock:
            if subscribed_topic in self._buffers:
                self._buffers[subscribed_topic].append(message)
            handler = self._message_handlers.get(subscribed_topic)
        if handler is not None:
            try:
                handler(message)
            except Exception:
                pass

    def _dispatch_local_message(self, topic: str, payload: bytes) -> None:
        with self._state_lock:
            subscribed_topics = list(self._subscribers.keys())
        for subscribed_topic in subscribed_topics:
            if not self._keyexpr_matches(subscribed_topic, topic):
                continue
            self._consume_message(
                subscribed_topic=subscribed_topic,
                message=self._build_message(topic=topic, raw_bytes=payload),
            )

    def _keyexpr_matches(self, pattern: str, topic: str) -> bool:
        if pattern == topic:
            return True
        escaped = re.escape(pattern)
        escaped = escaped.replace(r"\*\*", "__ZENOH_MULTI__")
        escaped = escaped.replace(r"\*", "[^/]*")
        escaped = escaped.replace("__ZENOH_MULTI__", ".*")
        return re.fullmatch(escaped, topic) is not None

    def _safe_undeclare(self, handle: Any) -> None:
        try:
            if hasattr(handle, "undeclare"):
                handle.undeclare()
            elif hasattr(handle, "close"):
                handle.close()
        except Exception:
            pass

    def _safe_close_session(self, session: Any) -> None:
        try:
            if hasattr(session, "close"):
                session.close()
            elif hasattr(session, "undeclare"):
                session.undeclare()
        except Exception:
            pass


_DEFAULT_CLIENT = ZenohServiceClient()


def initialize(auto_subscribe_defaults: bool = True) -> bool:
    return _DEFAULT_CLIENT.initialize(auto_subscribe_defaults=auto_subscribe_defaults)


def publish_topic(topic: str, payload: Any) -> bool:
    return _DEFAULT_CLIENT.publish(topic=topic, payload=payload)


def subscribe_topic(
    topic: str,
    buffer_size: Optional[int] = None,
    on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> bool:
    return _DEFAULT_CLIENT.subscribe(
        topic=topic,
        buffer_size=buffer_size,
        on_message=on_message,
    )


def stop_subscribe(topic: str) -> bool:
    return _DEFAULT_CLIENT.unsubscribe(topic=topic)


def subscribe_default_topics() -> bool:
    return _DEFAULT_CLIENT.subscribe_default_topics()


def poll_topic(topic: str, limit: int = 50) -> List[Dict[str, Any]]:
    return _DEFAULT_CLIENT.poll(topic=topic, limit=limit)


def recent_messages(topic: str, limit: int = 20) -> List[Dict[str, Any]]:
    return _DEFAULT_CLIENT.recent_messages(topic=topic, limit=limit)


def list_subscriptions() -> List[str]:
    return _DEFAULT_CLIENT.list_subscriptions()


def health() -> bool:
    return _DEFAULT_CLIENT.health()


def close_zenoh() -> bool:
    return _DEFAULT_CLIENT.close()


def get_last_error() -> str:
    return _DEFAULT_CLIENT.get_last_error()


def get_default_subscriptions() -> List[Dict[str, Any]]:
    return _DEFAULT_CLIENT.get_default_subscriptions()


def configure_default_paths(
    config_path: Optional[str | Path] = None,
    service_config_path: Optional[str | Path] = None,
) -> None:
    _DEFAULT_CLIENT.configure_default_paths(
        config_path=config_path,
        service_config_path=service_config_path,
    )


__all__ = [
    "ZenohServiceClient",
    "close_zenoh",
    "configure_default_paths",
    "get_default_subscriptions",
    "get_last_error",
    "health",
    "initialize",
    "list_subscriptions",
    "poll_topic",
    "publish_topic",
    "recent_messages",
    "stop_subscribe",
    "subscribe_default_topics",
    "subscribe_topic",
]
