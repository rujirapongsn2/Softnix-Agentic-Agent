import os
import resend

# Set the API key from environment variable or directly
resend.api_key = "re_XStv8vnv_ANJq3k7iCKDqH1GUmTpZcJ3V"

params: resend.Emails.SendParams = {
    "from": "Acme <onboarding@resend.dev>",
    "to": ["rujirapong@gmail.com"],
    "subject": "Test Email from Python Script",
    "html": "<strong>Hello! This is a test email sent from Python using Resend API.</strong><br><p>If you're reading this, the email was sent successfully!</p>",
}

try:
    email = resend.Emails.send(params)
    print(f"Email sent successfully! Response: {email}")
except Exception as e:
    print(f"Error sending email: {e}")