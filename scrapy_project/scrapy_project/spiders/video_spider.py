import scrapy


class VideoSpider(scrapy.Spider):
    name = "video_metadata"

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
    }

    def __init__(self, url=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not url:
            raise ValueError(
                "url argument is required"
            )

        self.start_urls = [url]

    def parse(self, response):
        title = response.css("title::text").get()

        description = response.css(
            'meta[name="description"]::attr(content)'
        ).get()

        thumbnail = response.css(
            'meta[property="og:image"]::attr(content)'
        ).get()

        video_url = response.css(
            'meta[property="og:video"]::attr(content)'
        ).get()

        yield {
            "url": response.url,
            "title": title,
            "description": description,
            "thumbnail": thumbnail,
            "video": video_url,
        }
