import base64
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase

from mailer.email_inline_images import (
    InlineImageEmailMultiAlternatives,
    inline_base64_images,
    inline_image_sources,
    load_image_attachments,
)
from mailer.management.commands.send_test_email import Command


class InlineImageEmailTests(SimpleTestCase):
    def test_inline_base64_images_rewrites_sources_and_deduplicates(self):
        image_data = base64.b64encode(b"fake-png-bytes").decode()
        html = (
            f'<img src="data:image/png;base64,{image_data}" alt="one">'
            f'<img src="data:image/png;base64,{image_data}" alt="two">'
        )

        rewritten_html, inline_images = inline_base64_images(html)

        self.assertEqual(rewritten_html.count("cid:"), 2)
        self.assertIn('src="cid:inline-', rewritten_html)
        self.assertEqual(len(inline_images), 1)
        self.assertEqual(inline_images[0].subtype, "png")
        self.assertEqual(inline_images[0].content, b"fake-png-bytes")

    def test_email_message_attaches_inline_images_as_related_parts(self):
        image_data = base64.b64encode(b"fake-png-bytes").decode()
        html = f'<img src="data:image/png;base64,{image_data}" alt="one">'
        rewritten_html, inline_images = inline_base64_images(html)

        message = InlineImageEmailMultiAlternatives(
            subject="Subject",
            body="Fallback body",
            from_email="sender@example.com",
            to=["recipient@example.com"],
            inline_images=inline_images,
        )
        message.attach_alternative(rewritten_html, "text/html")

        mime_message = message.message()
        parts = list(mime_message.iter_parts())

        self.assertEqual(mime_message.get_content_type(), "multipart/alternative")
        self.assertEqual(parts[0].get_content_type(), "text/plain")
        self.assertEqual(parts[1].get_content_type(), "multipart/related")

        related_parts = list(parts[1].iter_parts())
        self.assertEqual(related_parts[0].get_content_type(), "text/html")
        self.assertEqual(related_parts[1].get_content_type(), "image/png")
        self.assertEqual(related_parts[1]["Content-ID"], f"<{inline_images[0].content_id}>")

    @patch("mailer.email_inline_images.urlopen")
    def test_inline_image_sources_rewrites_remote_urls_to_cid(self, urlopen):
        response = MagicMock()
        response.read.return_value = b"remote-png-bytes"
        response.headers.get.return_value = "image/png"
        response.geturl.return_value = "https://example.com/logo.png"
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        urlopen.return_value = response

        html = '<img src="https://example.com/logo.png" alt="logo">'
        rewritten_html, inline_images = inline_image_sources(html)

        self.assertIn('src="cid:inline-', rewritten_html)
        self.assertEqual(len(inline_images), 1)
        self.assertEqual(inline_images[0].content, b"remote-png-bytes")
        self.assertEqual(inline_images[0].subtype, "png")
        urlopen.assert_called_once()

    def test_load_image_attachments_reads_local_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "logo.png"
            image_path.write_bytes(b"local-image-bytes")

            attachments = load_image_attachments([str(image_path)])

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].filename, "logo.png")
        self.assertEqual(attachments[0].content, b"local-image-bytes")
        self.assertEqual(attachments[0].mimetype, "image/png")

    @patch("mailer.management.commands.send_test_email.load_image_attachments")
    @patch("mailer.management.commands.send_test_email.InlineImageEmailMultiAlternatives")
    @patch("mailer.management.commands.send_test_email.inline_image_sources")
    @patch("mailer.management.commands.send_test_email.render_to_string")
    def test_send_test_email_converts_images_to_cid_and_attaches_files(
        self,
        render_to_string,
        inline_image_sources_mock,
        email_class,
        load_image_attachments_mock,
    ):
        raw_html = '<img src="https://example.com/logo.png" alt="one">'
        inline_html = '<img src="cid:inline-abc@mail.local" alt="one">'
        inline_images = [MagicMock()]
        attachments = [MagicMock(filename="logo.png", content=b"logo-bytes", mimetype="image/png")]
        render_to_string.return_value = raw_html
        inline_image_sources_mock.return_value = (inline_html, inline_images)
        load_image_attachments_mock.return_value = attachments
        email_instance = email_class.return_value

        Command().handle(
            emails=["recipient@example.com"],
            attachments=["/app/assets/logo.png"],
        )

        render_to_string.assert_called_once_with(
            "emails/test_email.html",
            {
                "app_name": "MyApp",
                "user_name": "Tester",
                "action_url": "https://example.com",
                "action_label": "Visit the App",
            },
        )
        inline_image_sources_mock.assert_called_once_with(raw_html)
        load_image_attachments_mock.assert_called_once_with(["/app/assets/logo.png"])
        email_class.assert_called_once_with(
            subject="[TEST] Email Render Check",
            body="This is a plain text fallback. Please enable HTML to view this email.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=["recipient@example.com"],
            inline_images=inline_images,
        )
        email_instance.attach_alternative.assert_called_once_with(inline_html, "text/html")
        email_instance.attach.assert_called_once_with("logo.png", b"logo-bytes", "image/png")
        email_instance.send.assert_called_once()
