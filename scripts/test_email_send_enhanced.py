import os
import resend


def send_test_email():
    """
    Function to send a test email using Resend API
    """
    # Set the API key
    resend.api_key = "re_XStv8vnv_ANJq3k7iCKDqH1GUmTpZcJ3V"

    params: resend.Emails.SendParams = {
        "from": "Acme <onboarding@resend.dev>",
        "to": ["rujirapong@gmail.com"],
        "subject": "Test Email from Python Script",
        "html": """
        <strong>Hello!</strong>
        <p>This is a test email sent from Python using Resend API.</p>
        <p>If you're reading this, the email was sent successfully!</p>
        """,
    }

    try:
        email = resend.Emails.send(params)
        print(f"✅ Email sent successfully!")
        print(f"📧 Email ID: {email['id']}")
        return email
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return None


if __name__ == "__main__":
    print("Sending test email...")
    result = send_test_email()
    if result:
        print("The email was sent successfully to rujirapong@gmail.com")
    else:
        print("Failed to send email")