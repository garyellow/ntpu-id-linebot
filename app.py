# -*- coding:utf-8 -*-
import math
import random
import string
import threading
import time

import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging.models import (
    Sender,
    QuickReply,
    QuickReplyItem,
    MessageAction,
    PostbackAction,
    TextMessage,
    ImageMessage,
    TemplateMessage,
    ConfirmTemplate,
    ButtonsTemplate,
)
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
    StickerMessageContent,
    FollowEvent,
    JoinEvent,
    MemberJoinedEvent,
)

from src.lineBotUtil import parser, reply_message
from src.requestUtil import (
    student_list,
    check_url,
    get_students_by_year_and_department,
)
from src.stickerUtil import stickers
from src.studentUtil import (
    DEPARTMENT_CODE,
    DEPARTMENT_NAME,
    FULL_DEPARTMENT_CODE,
    FULL_DEPARTMENT_NAME,
    Order,
    student_info_format,
    renew_student_list,
)

app = FastAPI()

url_state = False
renew_thread: threading.Thread


# 回覆者資訊
def get_sender_info() -> Sender:
    return Sender(
        name="學號魔術師",
        iconUrl=random.choice(stickers),
    )


# 學院 postback
def college_postback(college_name: str, year: str) -> PostbackAction:
    return PostbackAction(
        label=college_name,
        display_text=college_name,
        data=college_name + year,
        input_option="closeRichMenu",
    )


# 科系 postback
def department_postback(department_code: str, year: str) -> PostbackAction:
    return PostbackAction(
        label=FULL_DEPARTMENT_NAME[department_code],
        display_text="正在搜尋"
        + year
        + "學年度"
        + ("法律系" if department_code[0:2] == DEPARTMENT_CODE["法律"] else "")
        + DEPARTMENT_NAME[department_code]
        + ("組" if department_code[0:2] == DEPARTMENT_CODE["法律"] else "系"),
        data=year + " " + department_code,
        input_option="closeRichMenu",
    )


# 使用說明
async def instruction(event: MessageEvent | PostbackEvent) -> None:
    mes_sender = get_sender_info()
    messages = [
        TextMessage(
            text="輸入學號可查詢姓名\n輸入姓名可查詢學號\n輸入系名可查詢系代碼\n輸入系代碼可查詢系名\n輸入入學學年再選科系獲取學生名單",
            sender=mes_sender,
        ),
        TextMessage(
            text="For example~~\n學號：412345678\n姓名：林某某 or 某某\n系名：資工系 or 資訊工程學系\n系代碼：85\n"
            + "入學學年："
            + str(time.localtime(time.time()).tm_year - 1911)
            + " or "
            + str(time.localtime(time.time()).tm_year),
            sender=mes_sender,
        ),
        TextMessage(text="部分資訊是由學號推斷\n不一定為正確資料\n資料來源：國立臺北大學數位學苑2.0", sender=mes_sender),
    ]

    await reply_message(event.reply_token, messages)


@app.head("/")
@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(
        status_code=302, url="https://github.com/garyellow/ntpu-student-id-linebot"
    )


@app.head("/healthz")
@app.get("/healthz")
def healthz() -> PlainTextResponse:
    global url_state, renew_thread

    if not url_state:
        if not check_url():
            raise HTTPException(status_code=503, detail="Service Unavailable")

        renew_thread = threading.Thread(target=renew_student_list)
        renew_thread.start()

        url_state = True

    return PlainTextResponse(status_code=200, content="OK")


@app.post("/callback")
async def callback(request: Request) -> PlainTextResponse:
    global url_state

    # get X-Line-Signature header value
    signature = request.headers["X-Line-Signature"]

    # get request body as text
    body = await request.body()
    body = body.decode()

    # handle webhook body
    try:
        events = parser.parse(body, signature)

    except InvalidSignatureError:
        raise HTTPException(status_code=500, detail="Invalid signature")

    except requests.exceptions.Timeout:
        url_state = False
        raise HTTPException(status_code=408, detail="Request Timeout")

    for event in events:
        if isinstance(event, MessageEvent):
            if isinstance(event.message, TextMessageContent):
                await handle_text_message(event)
            if isinstance(event.message, StickerMessageContent):
                await handle_sticker_message(event)

        elif isinstance(event, PostbackEvent):
            await handle_postback_event(event)

        elif (
            isinstance(event, FollowEvent)
            or isinstance(event, JoinEvent)
            or isinstance(event, MemberJoinedEvent)
        ):
            await handle_follow_join_event(event)

    return PlainTextResponse(status_code=200, content="OK")


async def handle_text_message(event: MessageEvent) -> None:
    input_message = "".join(
        x for x in event.message.text if x not in string.whitespace + string.punctuation
    )

    if input_message.isdecimal():
        if input_message in FULL_DEPARTMENT_NAME:
            messages = [
                TextMessage(
                    text=FULL_DEPARTMENT_NAME[input_message],
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(
                                action=MessageAction(label="系代碼", text="系代碼")
                            ),
                        ]
                    ),
                    sender=get_sender_info(),
                ),
            ]

            await reply_message(event.reply_token, messages)

        elif 2 <= len(input_message) <= 4:
            year = (
                int(input_message)
                if int(input_message) < 1911
                else int(input_message) - 1911
            )

            messages = []
            if year > time.localtime(time.time()).tm_year - 1911:
                messages.append(
                    TextMessage(
                        text="你未來人？(⊙ˍ⊙)",
                        sender=get_sender_info(),
                    )
                )
            elif year < 90:
                messages.append(
                    TextMessage(
                        text="學校都還沒蓋好(￣▽￣)",
                        sender=get_sender_info(),
                    )
                )
            elif year < 95:
                messages.append(
                    TextMessage(
                        text="數位學苑還沒出生喔~~",
                        sender=get_sender_info(),
                    )
                )
            else:
                messages.append(
                    TemplateMessage(
                        alt_text="確認學年度",
                        template=ConfirmTemplate(
                            text="是否要搜尋 " + str(year) + " 學年度的學生",
                            actions=[
                                PostbackAction(
                                    label="哪次不是",
                                    display_text="哪次不是",
                                    data="搜尋全系" + str(year),
                                    input_option="openRichMenu",
                                ),
                                PostbackAction(
                                    label="我在想想",
                                    display_text="再啦乾ಠ_ಠ",
                                    data="兇",
                                    input_option="openKeyboard",
                                ),
                            ],
                        ),
                        sender=get_sender_info(),
                    )
                )

            await reply_message(event.reply_token, messages)

        elif 8 <= len(input_message) <= 9:
            students = student_info_format(
                input_message,
                order=[Order.YEAR, Order.FULL_DEPARTMENT, Order.NAME],
                space=2,
            )

            if not students:
                messages = [
                    TextMessage(
                        text="學號 " + input_message + " 不存在OAO",
                        sender=get_sender_info(),
                    ),
                ]

                await reply_message(event.reply_token, messages)
                return

            messages = [
                TextMessage(
                    text=students,
                    sender=get_sender_info(),
                ),
            ]

            if input_message[0] == "4":
                over_99 = len(input_message) == 9
                year = input_message[1 : over_99 + 3]

                department = input_message[over_99 + 3 : over_99 + 5]
                if department in [
                    DEPARTMENT_CODE["法律"],
                    DEPARTMENT_CODE["社學"][0:2],
                ]:
                    department += input_message[over_99 + 5]

                if department[0:2] == DEPARTMENT_CODE["法律"]:
                    show_text = (
                        "搜尋" + year + "學年度法律系" + DEPARTMENT_NAME[department] + "組"
                    )
                else:
                    show_text = "搜尋" + year + "學年度" + DEPARTMENT_NAME[department] + "系"

                messages[0].quick_reply = QuickReply(
                    items=[
                        QuickReplyItem(
                            action=PostbackAction(
                                label=show_text,
                                display_text="正在" + show_text,
                                data=year + " " + department,
                                input_option="closeRichMenu",
                            ),
                        ),
                    ],
                )

            await reply_message(event.reply_token, messages)

    else:
        if input_message in ["使用說明", "help"]:
            await instruction(event)

        elif input_message == "系代碼":
            students = "\n".join([x + "系 -> " + y for x, y in DEPARTMENT_CODE.items()])
            messages = [
                TextMessage(
                    text=students,
                    sender=get_sender_info(),
                ),
            ]

            await reply_message(event.reply_token, messages)

        elif input_message.strip("系") in DEPARTMENT_CODE:
            messages = [
                TextMessage(
                    text=DEPARTMENT_CODE[input_message.strip("系")],
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(
                                action=MessageAction(label="系代碼", text="系代碼")
                            ),
                        ]
                    ),
                    sender=get_sender_info(),
                ),
            ]

            await reply_message(event.reply_token, messages)

        elif input_message in FULL_DEPARTMENT_CODE:
            messages = [
                TextMessage(
                    text=FULL_DEPARTMENT_CODE[input_message],
                    quick_reply=QuickReply(
                        items=[
                            QuickReplyItem(
                                action=MessageAction(label="系代碼", text="系代碼")
                            ),
                        ]
                    ),
                    sender=get_sender_info(),
                ),
            ]

            await reply_message(event.reply_token, messages)

        elif input_message[0] in string.ascii_letters or len(input_message) < 6:
            students = []
            for key, value in student_list.items():
                if input_message in value:
                    students.append((key, value))

            messages = []
            if students:
                students = sorted(students, key=lambda x: (not len(x[0]), int(x[0])))

                for i in range(min(math.ceil(len(students) / 100), 5), 0, -1):
                    students_info = "\n".join(
                        [
                            student_info_format(x[0], x[1])
                            for x in students[
                                -i * 100 : -(i - 1) * 100 if i - 1 else None
                            ]
                        ]
                    )

                    messages.append(
                        TextMessage(
                            text=students_info,
                            sender=get_sender_info(),
                        )
                    )

                await reply_message(event.reply_token, messages)


async def handle_sticker_message(event: MessageEvent) -> None:
    sticker = random.choice(stickers)

    messages = [
        ImageMessage(
            original_content_url=sticker,
            preview_image_url=sticker,
            sender=Sender(iconUrl=sticker),
        ),
    ]

    await reply_message(event.reply_token, messages)


async def handle_postback_event(event: PostbackEvent) -> None:
    if event.postback.data == "使用說明":
        await instruction(event)

    elif event.postback.data == "兇":
        messages = [
            TextMessage(
                text="泥好兇喔~~இ௰இ",
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("搜尋全系"):
        year = event.postback.data.split("搜尋全系")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇學院群",
                template=ButtonsTemplate(
                    thumbnail_image_url="https://new.ntpu.edu.tw/assets/logo/ntpu_logo.png",
                    title="選擇學院群",
                    text="請選擇科系所屬學院群",
                    actions=[
                        college_postback("文法商", year),
                        college_postback("公社電資", year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("文法商"):
        year = event.postback.data.split("文法商")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇學院",
                template=ButtonsTemplate(
                    title="選擇學院",
                    text="請選擇科系所屬學院",
                    actions=[
                        college_postback("人文學院", year),
                        college_postback("法律學院", year),
                        college_postback("商學院", year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("公社電資"):
        year = event.postback.data.split("公社電資")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇學院",
                template=ButtonsTemplate(
                    title="選擇學院",
                    text="請選擇科系所屬學院",
                    actions=[
                        college_postback("公共事務學院", year),
                        college_postback("社會科學學院", year),
                        college_postback("電機資訊學院", year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("人文學院"):
        year = event.postback.data.split("人文學院")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇科系",
                template=ButtonsTemplate(
                    thumbnail_image_url="https://walkinto.in/upload/-192z7YDP8-JlchfXtDvI.JPG",
                    title="選擇科系",
                    text="請選擇要查詢的科系",
                    actions=[
                        department_postback(DEPARTMENT_CODE["中文"], year),
                        department_postback(DEPARTMENT_CODE["應外"], year),
                        department_postback(DEPARTMENT_CODE["歷史"], year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("法律學院"):
        year = event.postback.data.split("法律學院")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇組別",
                template=ButtonsTemplate(
                    thumbnail_image_url="https://walkinto.in/upload/byupdk9PvIZyxupOy9Dw8.JPG",
                    title="選擇組別",
                    text="請選擇要查詢的組別",
                    actions=[
                        department_postback(DEPARTMENT_CODE["法學"], year),
                        department_postback(DEPARTMENT_CODE["司法"], year),
                        department_postback(DEPARTMENT_CODE["財法"], year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("商學院"):
        year = event.postback.data.split("商學院")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇科系",
                template=ButtonsTemplate(
                    thumbnail_image_url="https://walkinto.in/upload/ZJum7EYwPUZkedmXNtvPL.JPG",
                    title="選擇科系",
                    text="請選擇科系 (休運系請直接點圖片)",
                    default_action=department_postback(DEPARTMENT_CODE["休運"], year),
                    actions=[
                        department_postback(DEPARTMENT_CODE["企管"], year),
                        department_postback(DEPARTMENT_CODE["金融"], year),
                        department_postback(DEPARTMENT_CODE["會計"], year),
                        department_postback(DEPARTMENT_CODE["統計"], year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("公共事務學院"):
        year = event.postback.data.split("公共事務學院")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇科系",
                template=ButtonsTemplate(
                    thumbnail_image_url="https://walkinto.in/upload/ZJhs4wEaDIWklhiVwV6DI.jpg",
                    title="選擇科系",
                    text="請選擇要查詢的科系",
                    actions=[
                        department_postback(DEPARTMENT_CODE["公行"], year),
                        department_postback(DEPARTMENT_CODE["不動"], year),
                        department_postback(DEPARTMENT_CODE["財政"], year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("社會科學學院"):
        year = event.postback.data.split("社會科學學院")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇科系",
                template=ButtonsTemplate(
                    thumbnail_image_url="https://walkinto.in/upload/WyPbshN6DIZ1gvZo2NTvU.JPG",
                    title="選擇科系",
                    text="請選擇科系",
                    actions=[
                        department_postback(DEPARTMENT_CODE["經濟"], year),
                        department_postback(DEPARTMENT_CODE["社學"], year),
                        department_postback(DEPARTMENT_CODE["社工"], year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    elif event.postback.data.startswith("電機資訊學院"):
        year = event.postback.data.split("電機資訊學院")[1]

        messages = [
            TemplateMessage(
                alt_text="選擇科系",
                template=ButtonsTemplate(
                    thumbnail_image_url="https://walkinto.in/upload/bJ9zWWHaPLWJg9fW-STD8.png",
                    title="選擇科系",
                    text="請選擇科系",
                    actions=[
                        department_postback(DEPARTMENT_CODE["電機"], year),
                        department_postback(DEPARTMENT_CODE["資工"], year),
                        department_postback(DEPARTMENT_CODE["通訊"], year),
                    ],
                ),
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)

    else:
        year, department = event.postback.data.split(" ")
        students = get_students_by_year_and_department(int(year), int(department))
        students_info = "\n".join(
            [
                student_info_format(x, y, [Order.ID, Order.NAME], 3)
                for x, y in students.items()
            ]
        )

        students_info += (
            "\n\n"
            + year
            + "學年度"
            + ("法律系" if department[0:2] == DEPARTMENT_CODE["法律"] else "")
            + DEPARTMENT_NAME[department]
            + ("組" if department[0:2] == DEPARTMENT_CODE["法律"] else "系")
            + "共有"
            + str(len(students))
            + "位學生"
        )

        messages = [
            TextMessage(
                text=students_info,
                sender=get_sender_info(),
            ),
        ]

        await reply_message(event.reply_token, messages)


async def handle_follow_join_event(event) -> None:
    mes_sender = get_sender_info()

    messages = [
        TextMessage(
            text="泥好~~我是學號姓名查詢小工具🔍\n可以用學號查詢到姓名\n也可以用姓名查詢到學號",
            sender=mes_sender,
        ),
        TextMessage(text="詳細使用說明請點選下方選單\n或輸入「使用說明」", sender=mes_sender),
        TextMessage(
            text="有疑問可以先去看常見問題\n若無法解決或有發現 Bug\n可以再到 GitHub 提出", sender=mes_sender
        ),
        TextMessage(text="部分資訊是由學號推斷\n不一定為正確資料\n資料來源：國立臺北大學數位學苑2.0", sender=mes_sender),
    ]

    await reply_message(event.reply_token, messages)
