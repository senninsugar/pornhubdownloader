BOT_NAME = "video_metadata_crawler"

SPIDER_MODULES = [
    "scrapy_project.spiders"
]

NEWSPIDER_MODULE = "scrapy_project.spiders"

ROBOTSTXT_OBEY = True

CONCURRENT_REQUESTS = 4

DOWNLOAD_DELAY = 1

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; VideoMetadataCrawler/1.0)"
)

FEEDS = {
    "metadata.json": {
        "format": "json",
        "encoding": "utf8",
        "indent": 2,
    }
}
