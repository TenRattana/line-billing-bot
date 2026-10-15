"""Thin async wrapper over line-bot-sdk with a cached stateless channel token."""

import asyncio
import logging
import time

from linebot.v3 import oauth
from linebot.v3.messaging import (
    ApiException,
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    FlexMessage,
    ImageMessage,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
    UserProfileResponse,
)

from app.config import (
    LINE_CHANNEL_ID,
    LINE_CHANNEL_SECRET,
)

logger = logging.getLogger(__name__)

TOKEN_REFRESH_MARGIN_SECONDS = 30.0

_client: AsyncApiClient | None = None
_token_expires_at = 0.0
_token_lock = asyncio.Lock()


async def _issue_token() -> tuple[str, float]:
    async with oauth.AsyncApiClient(oauth.Configuration()) as client:
        response = await oauth.AsyncChannelAccessToken(client).issue_stateless_channel_token(
            grant_type="client_credentials",
            client_id=LINE_CHANNEL_ID,
            client_secret=LINE_CHANNEL_SECRET,
        )

    return response.access_token, float(response.expires_in)


def _token_is_fresh() -> bool:
    return time.monotonic() < _token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS


async def _api_client() -> AsyncApiClient:
    global _client, _token_expires_at

    if _client and _token_is_fresh():
        return _client

    async with _token_lock:
        # Another request may have refreshed the token while we waited.
        if _client and _token_is_fresh():
            return _client

        token, expires_in = await _issue_token()

        if _client is None:
            _client = AsyncApiClient(Configuration(access_token=token))
        else:
            # The SDK copies the token into default headers at construction,
            # so a rotated token must be written to both places.
            _client.configuration.access_token = token
            _client.default_headers["Authorization"] = f"Bearer {token}"

        _token_expires_at = time.monotonic() + expires_in
        return _client


async def messaging() -> AsyncMessagingApi:
    return AsyncMessagingApi(await _api_client())


async def blob() -> AsyncMessagingApiBlob:
    return AsyncMessagingApiBlob(await _api_client())


async def access_token() -> str:
    """The current (auto-refreshed) channel token, for SDK modules with their own client (e.g. insight)."""
    return (await _api_client()).configuration.access_token


async def close() -> None:
    if _client:
        await _client.close()


async def reply_text(reply_token: str, text: str) -> None:
    await (await messaging()).reply_message(
        ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=text)])
    )


async def reply_flex(reply_token: str, flex_message: dict) -> None:
    await (await messaging()).reply_message(
        ReplyMessageRequest(reply_token=reply_token, messages=[FlexMessage.from_dict(flex_message)])
    )

async def push_text(user_id: str, text: str) -> None:
    await (await messaging()).push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=text)]))


async def push_flex(user_id: str, flex_message: dict) -> None:
    """For screens not answering a chat event (e.g. a LIFF action): no reply token."""
    await (await messaging()).push_message(
        PushMessageRequest(to=user_id, messages=[FlexMessage.from_dict(flex_message)])
    )


async def reply_text_and_image(
    reply_token: str,
    text: str,
    image_url: str,
) -> None:
    await (await messaging()).reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[
                TextMessage(text=text),
                ImageMessage(
                    original_content_url=image_url,
                    preview_image_url=image_url,
                ),
            ],
        )
    )


async def get_message_content(message_id: str) -> tuple[bytes, str]:
    response = await (await blob()).get_message_content_with_http_info(message_id)
    content_type = response.headers.get("content-type", "application/octet-stream")
    return bytes(response.data), content_type


async def get_profile(user_id: str) -> UserProfileResponse | None:
    """None when LINE won't share the profile (e.g. the user blocked the bot)."""
    try:
        return await (await messaging()).get_profile(user_id)
    except ApiException as error:
        logger.warning("get_profile failed for %s: HTTP %s", user_id, error.status)
        return None
