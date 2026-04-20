from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.conf import settings

from mailer.email_inline_images import (
    InlineImageEmailMultiAlternatives,
    inline_image_sources,
    load_image_attachments,
)


class Command(BaseCommand):
    help = 'Send a test HTML email to multiple addresses'

    def add_arguments(self, parser):
        parser.add_argument(
            '--emails',
            nargs='+',
            type=str,
            help='List of emails to send to (overrides default list)'
        )
        parser.add_argument(
            '--attachments',
            nargs='*',
            type=str,
            help='Local image files to attach to each email'
        )

    def handle(self, *args, **kwargs):

        # ── Your test recipients ──────────────────────────────
        recipients = kwargs['emails'] or [
            # 'elyoussfiihaamza@gmail.com', 
            # 'elyoussfi.hamza@ostorlab.dev' , 
            'zoulati.zakaria@ostorlab.dev' , 
            'zoulatizakaria3@outlook.com' , 
            # 'nouri@ostorlab.dev' , 
            # 'yasser.abassi@ostorlab.dev' , 
            # 'amine.atyq@ostorlab.dev' , 
        ]
        attachment_paths = kwargs.get('attachments') or []

        # ── Your template context ─────────────────────────────
        context = {
            # 'app_name': 'MyApp',
            # 'user_name': 'Tester',
            # 'action_url': 'https://example.com',
            # 'action_label': 'Visit the App',


            # Testing the scan follow up with account : 
            # template 1 
            'app_name': 'Tiktok',
            'package_name' : 'app.tiktok.org' , 
            'package_version' : '1.2.9' , 
            'vuln_1_count' : 11 , 
            'vuln_2_count' : 58 , 
            'vuln_3_count' : 4 , 
            'vuln_1_type' : 'HIGH' , 
            'vuln_2_type' : 'MEDIUM' , 
            'vuln_3_type' : 'LOW', 
            'app_image' : 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a6/Tiktok_icon.svg/960px-Tiktok_icon.svg.png' , 

            
        }

        # Render the template once, then rewrite supported image sources to
        # cid: references at send time. The template file itself stays intact.
        html_content = render_to_string('emails/test_email.html', context)
        # html_inline, inline_images = inline_image_sources(html_content)
        # try:
        #     attachments = load_image_attachments(attachment_paths)
        # except FileNotFoundError as exc:
        #     raise CommandError(str(exc)) from exc

        subject = '[TEST] Email Render Check'

        for email in recipients:
            msg = InlineImageEmailMultiAlternatives(
                subject=subject,
                body='This is a plain text fallback. Please enable HTML to view this email.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
                # inline_images=inline_images,
            )
            msg.attach_alternative(html_content, 'text/html')
            # for attachment in attachments:
            #     msg.attach(attachment.filename, attachment.content, attachment.mimetype)
            msg.send()
            self.stdout.write(self.style.SUCCESS(f'✓ Sent to {email}'))

        self.stdout.write(self.style.SUCCESS(f'\nDone! {len(recipients)} email(s) sent.'))
