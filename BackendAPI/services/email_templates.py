from typing import Dict, Any

def _base_template(content: str, preheader: str = "") -> str:
    """
    Drop branding wrapper for all emails.
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Drop</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #f6f9fc;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                margin-top: 40px;
                margin-bottom: 40px;
            }}
            .header {{
                text-align: center;
                padding: 30px 20px;
                background-color: #ffffff;
                border-bottom: 1px solid #eeeeee;
            }}
            .header img {{
                height: 40px;
            }}
            .content {{
                padding: 40px 30px;
                color: #333333;
                line-height: 1.6;
            }}
            .accent-color {{
                color: #d9a31b;
            }}
            .btn {{
                background-color: #d9a31b;
                color: #ffffff;
                text-decoration: none;
                padding: 12px 24px;
                border-radius: 6px;
                display: inline-block;
                font-weight: 600;
                margin-top: 20px;
            }}
            .footer {{
                background-color: #fcfcfc;
                padding: 20px;
                text-align: center;
                color: #888888;
                font-size: 13px;
                border-top: 1px solid #eeeeee;
            }}
            .preheader {{
                display: none;
                max-height: 0px;
                max-width: 0px;
                opacity: 0;
                overflow: hidden;
            }}
        </style>
    </head>
    <body>
        <div class="preheader">{preheader}</div>
        <div class="container">
            <div class="header">
                <!-- Replace with actual logo URL once you have it -->
                <h1 style="margin: 0; color: #d9a31b; font-size: 28px;">Drop</h1>
            </div>
            <div class="content">
                {content}
            </div>
            <div class="footer">
                &copy; 2026 Drop &middot; Nairobi, Kenya<br>
                This email was sent to you because you're a registered user of Drop.
            </div>
        </div>
    </body>
    </html>
    """

def welcome_customer(name: str) -> str:
    content = f"""
        <h2 style="margin-top:0;">Welcome to Drop, {name}! 💧</h2>
        <p>We're thrilled to have you here. Drop makes it incredibly easy to get water delivered straight to your door from trusted vendors.</p>
        <p>Ready to place your first order?</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="#" class="btn">Order Water Now</a>
        </div>
        <p>If you have any questions, feel free to reply to this email.</p>
    """
    return _base_template(content, preheader="Welcome to the Drop community!")

def welcome_vendor(name: str, business: str) -> str:
    content = f"""
        <h2 style="margin-top:0;">Welcome aboard, {name}! 🤝</h2>
        <p>Thank you for registering <strong>{business}</strong> with Drop.</p>
        <p>We are currently reviewing your business details and license. Once approved, you'll be able to start receiving orders from our wide network of customers.</p>
        <p>We'll notify you as soon as your account is verified.</p>
    """
    return _base_template(content, preheader="Your Drop Vendor application is under review.")

def welcome_rider(name: str) -> str:
    content = f"""
        <h2 style="margin-top:0;">Welcome to the Drop Delivery Network, {name}! 🚲</h2>
        <p>Thanks for signing up to deliver with Drop.</p>
        <p>We're reviewing your vehicle specific details and license. Once approved, you'll be able to go online and start earning money with flexible deliveries.</p>
        <p>We'll notify you as soon as your account is verified.</p>
    """
    return _base_template(content, preheader="Your Drop Rider application is under review.")

def password_reset(name: str, code: str) -> str:
    content = f"""
        <h2 style="margin-top:0;">Password Reset Request</h2>
        <p>Hi {name},</p>
        <p>We received a request to reset your password. Here is your verification code:</p>
        <div style="text-align: center; margin: 30px 0;">
            <div style="display:inline-block; font-size:32px; letter-spacing:8px; font-weight:bold; background:#f4f4f4; padding:15px 30px; border-radius:8px;">{code}</div>
        </div>
        <p>Enter this code in the app to reset your password. If you didn't request this, you can safely ignore this email.</p>
    """
    return _base_template(content, preheader=f"Your Drop reset code is {code}")

def order_confirmation(name: str, order: Dict[str, Any]) -> str:
    content = f"""
        <h2 style="margin-top:0;">Order Confirmed! 🎉</h2>
        <p>Hi {name},</p>
        <p>Your order <strong>#{order.get('id', '')}</strong> has been confirmed and is being processed by the vendor.</p>
        <div style="background-color: #f9f9f9; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 0 0 10px 0;"><strong>Total:</strong> KES {order.get('total_amount', '0.00')}</p>
            <p style="margin: 0;"><strong>Status:</strong> Processing</p>
        </div>
        <p>You can track the status of your order in the Drop Customer App.</p>
    """
    return _base_template(content, preheader="Your Drop order has been confirmed.")

def vendor_approved(name: str) -> str:
    content = f"""
        <h2 style="margin-top:0;">You're approved! 🎊</h2>
        <p>Hi {name},</p>
        <p>Great news! Your vendor account has been verified and approved.</p>
        <p>You can now log into the Drop Vendor app, list your products, and start receiving orders today.</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="#" class="btn">Open Vendor App</a>
        </div>
    """
    return _base_template(content, preheader="Your Drop Vendor account has been approved.")

def rider_approved(name: str) -> str:
    content = f"""
        <h2 style="margin-top:0;">You're approved to ride! 🛵</h2>
        <p>Hi {name},</p>
        <p>Great news! Your rider account has been verified and approved.</p>
        <p>You can now log into the Drop Rider app, go online, and start accepting delivery requests.</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="#" class="btn">Open Rider App</a>
        </div>
    """
    return _base_template(content, preheader="Your Drop Rider account has been approved.")


def _escape(value: str) -> str:
    """HTML-escape untrusted text before it goes into an email body.

    An administrator's message is not hostile, but it is free text typed into a
    console and dropped into HTML — an unescaped `<` silently swallows the rest
    of the paragraph, and a stray `&` renders as a broken entity. This is a
    correctness fix before it is a security one.
    """
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def broadcast(name: str, subject: str, body: str) -> str:
    """A message an administrator composed, in the platform's wrapper.

    Line breaks are converted to paragraphs rather than `<br>` runs: someone
    typing into a textarea separates thoughts with a blank line, and honouring
    that is the difference between a readable email and a wall.
    """
    paragraphs = "".join(
        f'<p style="color: #374151; font-size: 15px; line-height: 1.7; margin: 0 0 16px;">{_escape(block.strip())}</p>'
        for block in body.split("\n\n")
        if block.strip()
    )

    return f"""
    <div style="padding: 32px;">
        <h1 style="color: #111827; font-size: 22px; margin: 0 0 8px;">{_escape(subject)}</h1>
        <p style="color: #6b7280; font-size: 14px; margin: 0 0 24px;">Hi {_escape(name)},</p>
        {paragraphs}
        <p style="color: #9ca3af; font-size: 12px; margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 16px;">
            You are receiving this because you have a Drop account.
            Manage what we send you in the app under Settings &rarr; Notifications.
        </p>
        <p style="color: #9ca3af; font-size: 12px;">&copy; Drop Water Delivery</p>
    </div>
    """


def support_reply(name: str, subject: str, body: str, ticket_id: str) -> str:
    """A response to a support ticket."""
    paragraphs = "".join(
        f'<p style="color: #374151; font-size: 15px; line-height: 1.7; margin: 0 0 16px;">{_escape(block.strip())}</p>'
        for block in body.split("\n\n")
        if block.strip()
    )

    return f"""
    <div style="padding: 32px;">
        <p style="color: #6b7280; font-size: 14px; margin: 0 0 4px;">Re: your message to Drop support</p>
        <h1 style="color: #111827; font-size: 20px; margin: 0 0 24px;">{_escape(subject)}</h1>
        <p style="color: #6b7280; font-size: 14px; margin: 0 0 16px;">Hi {_escape(name)},</p>
        {paragraphs}
        <p style="color: #6b7280; font-size: 14px; line-height: 1.6; margin-top: 24px;">
            Reply in the Drop app to continue this conversation &mdash; that keeps
            everything in one place and reaches us fastest.
        </p>
        <p style="color: #9ca3af; font-size: 12px; margin-top: 32px;">
            Reference {_escape(ticket_id[:8])} &middot; &copy; Drop Water Delivery
        </p>
    </div>
    """
