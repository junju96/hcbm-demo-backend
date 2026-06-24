import json
import time

from zenoh_service import (
    close_zenoh,
    get_last_error,
    initialize,
    list_subscriptions,
    poll_topic,
    subscribe_topic,
    publish_topic,
)


def handle_message(message: dict) -> None:
    if message["topic"] == "op/t01/g01/vUGV_001/status/motion":
        print("callback message:", json.dumps(message, ensure_ascii=False))
    elif message["topic"] == "demo/topic":
        print("demo message:", json.dumps(message, ensure_ascii=False))


def main() -> None:
    if not initialize(auto_subscribe_defaults=True):
        print("initialize failed:", get_last_error())
        return

    # if not subscribe_topic("op/**", buffer_size=200, on_message=handle_message):
    #     print("subscribe failed:", get_last_error())
    #     close_zenoh()
    #     return

    subscribe_topic("demo/topic", buffer_size=200, on_message=handle_message)

    time.sleep(0.5)

    for i in range(10):
        publish_topic("demo/topic", {"msg": f"hello {i}"})
        time.sleep(0.5)
    print("subscriptions:", list_subscriptions())
    print(
        "messages:",
        json.dumps(poll_topic("op/**", limit=1000), ensure_ascii=False, indent=2),
    )
    time.sleep(10)
    print("close ok:", close_zenoh())


if __name__ == "__main__":
    main()
