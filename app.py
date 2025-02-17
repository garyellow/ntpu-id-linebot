# -*- coding:utf-8 -*-
from asyncio import gather, sleep

from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    FollowEvent,
    JoinEvent,
    MemberJoinedEvent,
    MessageEvent,
    PostbackEvent,
    StickerMessageContent,
    TextMessageContent,
)
from sanic import (
    HTTPResponse,
    Request,
    Sanic,
    ServiceUnavailable,
    Unauthorized,
    empty,
    redirect,
)

from ntpu_linebot import (
    LINE_API_UTIL,
    STICKER,
    handle_follow_join_event,
    handle_postback_event,
    handle_sticker_message,
    handle_text_message,
    ntpu_contact,
    ntpu_course,
    ntpu_id,
)

app = Sanic(__name__)


@app.before_server_start
async def before_server_start(sanic: Sanic):
    """
    Async function called before the server starts.

    Args:
        sanic (Sanic): The Sanic application instance.
    """

    while not all(
        await gather(
            STICKER.load_stickers(),
            ntpu_id.healthz(sanic),
            ntpu_contact.healthz(sanic),
            ntpu_course.healthz(sanic),
        )
    ):
        await sleep(1)


@app.route("/", methods=["HEAD", "GET"])
async def index(_: Request) -> HTTPResponse:
    """Redirects to the project GitHub page"""

    return redirect("https://github.com/garyellow/ntpu-linebot")


@app.route("/healthz", methods=["HEAD", "GET"])
async def healthz(_: Request) -> HTTPResponse:
    """Checks the health status."""

    return empty()


@app.route("/healthy", methods=["HEAD", "GET"])
async def healthy(request: Request) -> HTTPResponse:
    """
    Asynchronous function for checking the health status of various services.

    Args:
        request (Request): The request object.

    Returns:
        HTTPResponse: Response object indicating the health status.
    """

    if not await ntpu_id.healthz(request.app):
        raise ServiceUnavailable("ID Service Unavailable")

    if not await ntpu_contact.healthz(request.app):
        raise ServiceUnavailable("Contact Service Unavailable")

    if not await ntpu_course.healthz(request.app):
        raise ServiceUnavailable("Course Service Unavailable")

    return empty()


@app.route("/callback", methods=["POST"])
async def callback(request: Request) -> HTTPResponse:
    """
    Handle LINE Bot webhook events.

    Args:
        request (Request): The request object representing the incoming webhook request.

    Returns:
        HTTPResponse: The response object indicating the success of the callback function.

    Raises:
        ServiceUnavailable: If any of the services (ID, Contact, Course) are unavailable.
        Unauthorized: If the request signature is invalid.
    """

    if not all(
        await gather(
            *[
                ntpu_id.healthz(request.app),
                ntpu_contact.healthz(request.app),
                ntpu_course.healthz(request.app),
            ]
        )
    ):
        raise ServiceUnavailable("Service Unavailable")

    try:
        events = LINE_API_UTIL.parser.parse(
            request.body.decode(),
            request.headers.get("X-Line-Signature"),
        )

        for event in events:
            await LINE_API_UTIL.loading_message(event.source.user_id)

            if isinstance(event, MessageEvent):
                if isinstance(event.message, TextMessageContent):
                    request.app.add_task(handle_text_message(event))

                elif isinstance(event.message, StickerMessageContent):
                    request.app.add_task(handle_sticker_message(event))

            elif isinstance(event, PostbackEvent):
                request.app.add_task(handle_postback_event(event))

            elif isinstance(event, (FollowEvent, JoinEvent, MemberJoinedEvent)):
                request.app.add_task(handle_follow_join_event(event))

        return empty()

    except InvalidSignatureError as exc:
        raise Unauthorized("Invalid signature") from exc
