from __future__ import annotations

from abc import ABC, abstractmethod


class BasePublisher(ABC):
    """Abstract plugin for publishing to a social network.

    Each subclass implements validate() and publish().
    The service layer calls each enabled publisher independently so that
    one network failure never blocks another.
    """

    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger

    @abstractmethod
    def validate(self) -> dict:
        """Verify credentials / target exist and are usable."""

    @abstractmethod
    def publish(self, *, media_path: str, text: str, details: str = "") -> tuple[str, str | None, str | None]:
        """Publish to the platform.

        Returns (platform_id, public_url, extra_url).
        - media_path : local path to image or video
        - text       : main caption / title
        - details    : supplementary text (FB comment, YT description …)
        - extra_url  : direct URL to the auto-posted detailed comment (None if
          the platform has no such feature or the post failed).
        """
