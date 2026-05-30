"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ClipboardCopyIcon, CheckIcon } from "lucide-react";
import { toast } from "sonner";

import { useMe } from "@/hooks/useMe";
import { testTwilio } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const WEBHOOK_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "https://your-api.example.com";
const WEBHOOK_URL = `${WEBHOOK_BASE}/webhook/twilio`;

function CodeBlock({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="group relative rounded-lg bg-muted px-4 py-3 font-mono text-sm">
      <span className="break-all">{children}</span>
      <button
        type="button"
        onClick={copy}
        aria-label="Copy to clipboard"
        className="absolute right-2 top-2 hidden rounded p-1 text-muted-foreground hover:bg-background hover:text-foreground group-hover:flex"
      >
        {copied ? (
          <CheckIcon className="size-4 text-green-500" />
        ) : (
          <ClipboardCopyIcon className="size-4" />
        )}
      </button>
    </div>
  );
}

interface TestResult {
  success: boolean;
  message: string;
}

export default function TwilioPage() {
  const router = useRouter();
  const { data: me } = useMe();
  const clinicId = me?.clinic?.id;

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  async function handleTest() {
    if (!clinicId) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testTwilio(clinicId);
      setTestResult(result);
      if (result.success) {
        toast.success("Test message sent successfully");
      } else {
        toast.error(result.message ?? "Test failed");
      }
    } catch {
      const fallback: TestResult = {
        success: false,
        message: "Could not reach the server. Check your API URL.",
      };
      setTestResult(fallback);
      toast.error(fallback.message);
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold">Twilio Setup</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect your Twilio WhatsApp number to ClinicAI by pointing its
          webhook here.
        </p>
      </div>

      {/* Webhook URL */}
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium">Your webhook URL</h2>
        <CodeBlock>{WEBHOOK_URL}</CodeBlock>
        <p className="text-xs text-muted-foreground">
          Paste this URL into the Twilio webhook field below.
        </p>
      </section>

      {/* Step-by-step guide */}
      <section className="flex flex-col gap-4">
        <h2 className="text-sm font-medium">How to configure Twilio</h2>
        <ol className="flex flex-col gap-4">
          {[
            {
              step: 1,
              title: "Open the Twilio Console",
              body: (
                <p className="text-sm text-muted-foreground">
                  Go to{" "}
                  <a
                    href="https://console.twilio.com"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline underline-offset-2 hover:text-foreground"
                  >
                    console.twilio.com
                  </a>{" "}
                  and sign in.
                </p>
              ),
            },
            {
              step: 2,
              title: 'Navigate to Messaging → Senders → WhatsApp Senders',
              body: (
                <p className="text-sm text-muted-foreground">
                  In the left sidebar go to <strong>Messaging</strong>, then{" "}
                  <strong>Senders</strong>, then click{" "}
                  <strong>WhatsApp Senders</strong>.
                </p>
              ),
            },
            {
              step: 3,
              title: "Edit your WhatsApp sender",
              body: (
                <p className="text-sm text-muted-foreground">
                  Click the three-dot menu next to your approved WhatsApp number
                  and choose <strong>Edit</strong>.
                </p>
              ),
            },
            {
              step: 4,
              title: "Paste the webhook URL",
              body: (
                <div className="flex flex-col gap-2">
                  <p className="text-sm text-muted-foreground">
                    In the <strong>When a message comes in</strong> field, paste:
                  </p>
                  <CodeBlock>{WEBHOOK_URL}</CodeBlock>
                </div>
              ),
            },
            {
              step: 5,
              title: 'Set HTTP method to POST and save',
              body: (
                <p className="text-sm text-muted-foreground">
                  Make sure the HTTP method is set to <strong>HTTP POST</strong>,
                  then click <strong>Save</strong>.
                </p>
              ),
            },
          ].map(({ step, title, body }) => (
            <li key={step} className="flex gap-4">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                {step}
              </span>
              <div className="flex flex-col gap-1.5 pt-0.5">
                <p className="text-sm font-medium">{title}</p>
                {body}
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Test message */}
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium">Verify the connection</h2>
        <p className="text-sm text-muted-foreground">
          Send a test message to confirm the webhook is reachable.
        </p>
        <div>
          <Button
            variant="outline"
            onClick={handleTest}
            disabled={testing || !clinicId}
          >
            {testing ? "Sending…" : "Send Test Message"}
          </Button>
        </div>

        {testResult && (
          <Card className={testResult.success ? "border-green-500/40" : "border-destructive/40"}>
            <CardHeader>
              <CardTitle className={testResult.success ? "text-green-600" : "text-destructive"}>
                {testResult.success ? "Success" : "Failed"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{testResult.message}</p>
            </CardContent>
          </Card>
        )}
      </section>

      <div className="flex justify-end">
        <Button onClick={() => router.push("/onboarding/done")} size="lg">
          Continue
        </Button>
      </div>
    </div>
  );
}
