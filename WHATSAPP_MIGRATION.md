# Switching from Twilio to Meta WhatsApp Cloud API

## Cost saving
Twilio: ~$0.0084/msg → Meta direct: ~$0.0034/msg → 60% reduction

## Setup steps
1. Go to developers.facebook.com → Create App → Business type
2. Add "WhatsApp" product to your app
3. Get your Phone Number ID and Temporary Access Token from the API Setup section
4. Generate a Permanent Access Token via System User in Business Settings
5. Set webhook URL in your Meta app:
   - URL: https://YOUR_DOMAIN/webhook/whatsapp
   - Verify Token: value of META_VERIFY_TOKEN in .env
   - Subscribe to: messages, message_reactions
6. Add these to .env:
   META_PHONE_NUMBER_ID=...
   META_ACCESS_TOKEN=...
   META_VERIFY_TOKEN=clinicai_webhook_verify_2026
7. Update DOCTOR_WHATSAPP_NUMBERS to use plain E.164 format (+91XXXXXXXXXX, no whatsapp: prefix)
8. Restart: uvicorn main:app --reload

## Number format change
- Old (Twilio): whatsapp:+919801581020
- New (Meta): +919801581020
- The code normalizes both formats, but update your .env DOCTOR_WHATSAPP_NUMBERS

## Interactive buttons
Appointment approval buttons now use Meta's native button format.
Button IDs: approve_{id} / reject_{id} / suggest_{id}
Doctors tap the same buttons — no UX change.

## Test the webhook
curl -X GET "https://YOUR_DOMAIN/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=clinicai_webhook_verify_2026&hub.challenge=test123"
Should return: test123
