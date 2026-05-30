import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Twilio Setup – ClinicAI Docs",
  description: "Connect a Twilio WhatsApp number to ClinicAI.",
};

function Step({
  number,
  title,
  children,
}: {
  number: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-5 mb-8 last:mb-0">
      <div className="flex flex-col items-center">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-sm font-semibold text-white">
          {number}
        </div>
        <div className="mt-2 flex-1 w-px bg-zinc-200" />
      </div>
      <div className="pb-2">
        <h3 className="text-base font-semibold text-zinc-900 mb-2">{title}</h3>
        <div className="text-sm text-zinc-600 leading-relaxed space-y-2">
          {children}
        </div>
      </div>
    </div>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="rounded-lg bg-zinc-950 text-zinc-100 text-xs px-4 py-3 overflow-x-auto font-mono leading-relaxed">
      <code>{children}</code>
    </pre>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 my-4">
      <span className="font-semibold">Note: </span>
      {children}
    </div>
  );
}

export default function TwilioSetupPage() {
  return (
    <article>
      <h1 className="text-2xl font-bold text-zinc-900 mb-2">Twilio Setup</h1>
      <p className="text-zinc-500 text-sm mb-10">
        ClinicAI uses Twilio to send and receive WhatsApp messages. This guide
        walks you through connecting your Twilio account.
      </p>

      <Note>
        Twilio offers a <strong>Sandbox</strong> number for testing and a{" "}
        <strong>Production</strong> number for live clinics. The sandbox
        requires patients to opt in by sending a join code. For a real clinic
        you will need a production WhatsApp Business-approved number — this
        typically takes 1–3 business days to provision.
      </Note>

      <div className="mt-8">
        <Step number={1} title="Create a Twilio account">
          <p>
            Go to{" "}
            <a
              href="https://www.twilio.com/try-twilio"
              target="_blank"
              rel="noopener noreferrer"
              className="underline text-zinc-900"
            >
              twilio.com/try-twilio
            </a>{" "}
            and sign up for a free account. Verify your email and phone number.
          </p>
        </Step>

        <Step number={2} title="Enable the WhatsApp Sandbox (for testing)">
          <p>
            In the Twilio Console, navigate to{" "}
            <strong>Messaging → Try it out → Send a WhatsApp message</strong>.
            You will see the sandbox number and a join code (e.g.{" "}
            <code className="bg-zinc-100 text-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono">
              join bright-elephant
            </code>
            ).
          </p>
          <p>
            Send that code from your own WhatsApp to{" "}
            <code className="bg-zinc-100 text-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono">
              +1 415 523 8886
            </code>{" "}
            to opt in. Anyone testing the clinic must do the same.
          </p>
          <Note>
            The sandbox QR code is shown on this page. You can share it with
            staff for easy opt-in during testing — scan it with WhatsApp camera
            and it will send the join code automatically.
          </Note>
        </Step>

        <Step number={3} title="Retrieve your credentials">
          <p>
            From the Twilio Console dashboard, copy your{" "}
            <strong>Account SID</strong> and <strong>Auth Token</strong>. Also
            note the sandbox WhatsApp number:
          </p>
          <CodeBlock>{`TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886`}</CodeBlock>
          <p>Add these to your environment variables / Vercel project settings.</p>
        </Step>

        <Step number={4} title="Deploy ClinicAI and get your webhook URL">
          <p>
            Deploy your backend so it has a public HTTPS URL. Your webhook
            endpoint follows this pattern:
          </p>
          <CodeBlock>{`https://<your-domain>/api/twilio/webhook`}</CodeBlock>
          <p>
            For local development you can use{" "}
            <a
              href="https://ngrok.com"
              target="_blank"
              rel="noopener noreferrer"
              className="underline text-zinc-900"
            >
              ngrok
            </a>{" "}
            to expose your local server:
          </p>
          <CodeBlock>{`ngrok http 3000
# copy the https forwarding URL, e.g.:
# https://a1b2c3d4.ngrok.io/api/twilio/webhook`}</CodeBlock>
        </Step>

        <Step number={5} title="Set the webhook in Twilio">
          <p>
            In the Twilio Console go to{" "}
            <strong>
              Messaging → Settings → WhatsApp Sandbox Settings
            </strong>{" "}
            (or your production number&apos;s configuration page).
          </p>
          <p>
            Set the <strong>When a message comes in</strong> webhook to your
            URL and choose <strong>HTTP POST</strong>:
          </p>
          <CodeBlock>{`https://<your-domain>/api/twilio/webhook`}</CodeBlock>
          <p>Save the settings.</p>
        </Step>

        <Step number={6} title="Request a production WhatsApp number">
          <p>
            When you are ready for live patients, submit a WhatsApp Business
            profile through Twilio:
          </p>
          <ol className="list-decimal list-inside space-y-1 pl-2">
            <li>
              Go to <strong>Messaging → Senders → WhatsApp Senders</strong>
            </li>
            <li>Click <strong>Request a number</strong></li>
            <li>
              Fill in your clinic&apos;s display name, description, and business
              details
            </li>
            <li>
              Submit — Meta typically approves in 1–3 business days
            </li>
          </ol>
          <p>
            Once approved, replace{" "}
            <code className="bg-zinc-100 text-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono">
              TWILIO_WHATSAPP_FROM
            </code>{" "}
            in your environment with the new production number and update the
            webhook URL on that sender.
          </p>
        </Step>

        <Step number={7} title="Verify the integration">
          <p>
            Send a WhatsApp message to your clinic number and confirm a reply
            arrives. Check the ClinicAI dashboard under{" "}
            <strong>Activity → Messages</strong> to see the inbound event
            logged.
          </p>
        </Step>
      </div>
    </article>
  );
}
