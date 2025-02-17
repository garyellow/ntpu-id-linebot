# -*- coding:utf-8 -*-
from asyncio import gather

from httpx import AsyncClient, HTTPError, Timeout
from bs4 import BeautifulSoup as Bs4
from fake_useragent import UserAgent


class StickerUtil:
    __SPY_FAMILY_URLS = [
        "https://spy-family.net/tvseries/special/special1_season1.php",
        "https://spy-family.net/tvseries/special/special2_season1.php",
        "https://spy-family.net/tvseries/special/special9_season1.php",
        "https://spy-family.net/tvseries/special/special13_season1.php",
        "https://spy-family.net/tvseries/special/special16_season1.php",
        "https://spy-family.net/tvseries/special/special17_season1.php",
        "https://spy-family.net/tvseries/special/special3.php",
    ]
    __ICHIGO_PRODUCTION_URL = "https://ichigoproduction.com/special/present_icon.html"
    __UA = UserAgent(min_percentage=0.01)
    STICKER_LIST: list[str] = []

    async def _fetch_spy_family_stickers(
        self, client: AsyncClient, url: str
    ) -> list[str]:
        """
        從 Spy Family 網站抓取貼圖連結

        Args:
            session (ClientSession): The aiohttp client session.
            url (str): The URL to fetch the stickers from.

        Returns:
            list[str]: A list of sticker URLs.
        """

        stickers = []
        try:
            res = await client.get(url)
            if res.status_code == 200:
                soup = Bs4(res.text, "lxml")
                for i in soup.select("ul.icondlLists > li > a"):
                    if href := i.get("href"):
                        stickers.append(
                            f"https://spy-family.net/tvseries/{href[3:]}"
                        )

        except HTTPError as e:
            print(f"Error fetching {url}: {str(e)}")

        return stickers

    async def _fetch_ichigo_stickers(self, client: AsyncClient) -> list[str]:
        """
        從 Ichigo Production 網站抓取貼圖連結

        Returns:
            list[str]: A list of sticker URLs in the format "https://ichigoproduction.com/{path}"
        """

        stickers = []
        try:
            res = await client.get(self.__ICHIGO_PRODUCTION_URL)
            if res.status_code == 200:
                soup = Bs4(res.text, "lxml")
                for i in soup.select("ul.tp5 > li > div.ph > a"):
                    if href := i.get("href"):
                        stickers.append(f"https://ichigoproduction.com/{href[3:]}")

        except HTTPError as e:
            print(f"Error fetching Ichigo: {str(e)}")

        return stickers

    async def load_stickers(self) -> bool:
        """並行載入所有貼圖"""

        async with AsyncClient(
            timeout=Timeout(10),
            headers={"User-Agent": self.__UA.random},
        ) as client:
            spy_family_tasks = [
                self._fetch_spy_family_stickers(client, url)
                for url in self.__SPY_FAMILY_URLS
            ]

            all_tasks = spy_family_tasks + [self._fetch_ichigo_stickers(client)]

            results = await gather(*all_tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, list):
                    self.STICKER_LIST.extend(result)

        return len(self.STICKER_LIST) > 0


STICKER = StickerUtil()
