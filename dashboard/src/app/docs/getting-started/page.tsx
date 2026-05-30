import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Getting Started – ClinicAI Docs",
  description: "Set up ClinicAI for your clinic in six steps.",
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
    <div className="flex gap-5">
      <div className="flex flex-col items-center">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-sm font-semibold text-white">
          {number}
        </div>
        <div className="mt-2 flex-1 w-px bg-zinc-200 last:hidden" />
      </div>
      <div className="pb-10">
        <h3 className="text-base font-semibold text-zinc-900 mb-2">{title}</h3>
        <div className="text-sm text-zinc-600 leading-relaxed space-y-3">
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

export default function GettingStartedPage() {
  return (
    <article>
      <h1 className="text-2xl font-bold text-zinc-900 mb-2">Getting Started</h1>
      <p className="text-zinc-500 text-sm mb-10">
        Go from zero to live in under 30 minutes. Follow the steps below to
        configure your ClinicAI workspace.
      </p>

      <div>
        <Step number={1} title="Sign up">
          <p>
            Create your account at{" "}
            <code className="bg-zinc-100 text-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono">
              app.clinicai.io/auth/signup
            </code>
            . Enter your name, clinic name, and work email. A verification link
            will be sent — click it to activate your account.
          </p>
        </Step>

        <Step number={2} title="Configure your clinic">
          <p>
            In <strong>Settings → Clinic Profile</strong>, fill in your clinic
            name, timezone, and working hours. These values drive appointment
            slot generation and the after-hours queue message sent to patients.
          </p>
        </Step>

        <Step number={3} title="Add doctors">
          <p>
            Navigate to <strong>Doctors → Invite</strong>. Enter each
            doctor&apos;s name and WhatsApp number (with country code, e.g.{" "}
            <code className="bg-zinc-100 text-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono">
              +923001234567
            </code>
            ). Each doctor will receive a WhatsApp message asking them to opt in.
          </p>
        </Step>

        <Step number={4} title="Set AI model">
          <p>
            Go to <strong>Settings → AI Model</strong> and choose the LLM that
            best suits your clinic. See the{" "}
            <a href="/docs/ai-models" className="underline text-zinc-900">
              AI Models guide
            </a>{" "}
            for a comparison. Paste the relevant API key into the field provided.
          </p>
        </Step>

        <Step number={5} title="Configure Twilio">
          <p>
            You need a Twilio WhatsApp-enabled number to receive and send
            patient messages. Follow the{" "}
            <a href="/docs/twilio-setup" className="underline text-zinc-900">
              Twilio Setup guide
            </a>
            , then paste your webhook URL into the Twilio console. The webhook
            URL has the following format:
          </p>
          <CodeBlock>{`https://<your-domain>/api/twilio/webhook`}</CodeBlock>
          <p>
            Set the environment variables in your deployment environment (or
            <code className="bg-zinc-100 text-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono mx-1">
              .env.local
            </code>
            for local development):
          </p>
          <CodeBlock>{`# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# AI model (pick one)
GROQ_API_KEY=gsk_...
# or
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
# or
GOOGLE_API_KEY=AIza...

# Misc
CLINIC_TIMEZONE=Asia/Karachi
NEXTAUTH_SECRET=your_nextauth_secret
DATABASE_URL=postgresql://...`}</CodeBlock>
        </Step>

        <Step number={6} title="Go live">
          <p>
            Deploy your backend (see{" "}
            <code className="bg-zinc-100 text-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono">
              AGENTS.md
            </code>{" "}
            for deployment notes), update the Twilio webhook to your production
            URL, and send a test WhatsApp message to your clinic number.
            You&apos;re live.
          </p>
        </Step>
      </div>
    </article>
  );
}
