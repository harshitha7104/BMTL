import React, { useEffect, useState } from 'react';
import { AlertTriangle, Battery, Camera, CheckCircle2, FileBarChart, HelpCircle, Library, Mail, Mic, ShieldCheck, XCircle } from 'lucide-react';
import { listCopilotProviders } from '../services/copilotService';

/** Plain-language help: how to use ScrapTrust, what it can and cannot do, privacy, and who to ask. */
const STEPS = [
  { icon: Battery, title: 'Check a black-mass reading', body: 'Type the numbers from your XRF gun in the message box, for example: Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4. Press send.' },
  { icon: Camera, title: 'Use a photo instead', body: 'Press + and choose "Take a photo". Hold the phone straight above the gun screen, avoid glare, and fill the picture with the numbers. Always check the numbers ScrapTrust read against the photo.' },
  { icon: FileBarChart, title: 'Compare bags and make a report', body: 'After a few readings, type "compare these" to see which bag is different, or "make a Word report" to get a file you can share.' },
  { icon: Mic, title: 'Talk instead of typing', body: 'Press the microphone to dictate, or press Talk (top right on a computer, above the message box on a phone) for a hands-free conversation where ScrapTrust answers out loud.' },
  { icon: Library, title: 'Find things later', body: 'Everything you upload, every check and every report is kept in your Library. You can search, rename, pin, open, and download as text or PDF.' },
];

const FAQ = [
  ['What do OBSERVED and INFERRED mean?', 'OBSERVED is what the gun actually read. INFERRED is ScrapTrust\'s estimate of what a lab would measure. The "likely range" shows where the lab value will probably be (9 times out of 10).'],
  ['Why is lithium "calculated"?', 'Handheld XRF guns cannot see lithium. ScrapTrust calculates it from the nickel, cobalt, manganese and iron it does see. Always confirm lithium with a lab test.'],
  ['Can I use these numbers to set a price?', 'No. The numbers are estimates to help you decide what to test and how to sort. Prices must be based on a lab (ICP-OES) result.'],
  ['The answer looks wrong. What should I do?', 'Press the thumbs-down under the answer and say what is wrong. Check the gun numbers you typed or that were read from the photo. If a value is far from what you expect, send that bag to the lab.'],
  ['What does "low confidence" mean?', 'The reading does not look much like the samples ScrapTrust was trained on. Treat the result with extra care and confirm it with a lab test.'],
  ['Can I delete something?', 'You can remove items from your Library and delete whole conversations from the side menu. ACE Green keeps a record of activity for quality and safety checks.'],
];

export default function HelpPage() {
  const [contact, setContact] = useState('');
  useEffect(() => { listCopilotProviders().then(r => setContact((r as { support_contact?: string }).support_contact || '')).catch(() => undefined); }, []);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-8 text-ace-ink">
        <div className="mb-6 flex items-center gap-3">
          <HelpCircle className="h-6 w-6 text-ace-terracotta" />
          <h1 className="text-2xl font-normal">Help</h1>
        </div>

        <h2 className="mb-3 text-lg font-medium">How to use ScrapTrust</h2>
        <div className="mb-8 space-y-3">
          {STEPS.map(s => (
            <div key={s.title} className="flex gap-3 rounded-2xl border border-ace-line bg-white/70 p-4">
              <s.icon className="mt-0.5 h-5 w-5 shrink-0 text-ace-terracotta" />
              <div><p className="font-medium">{s.title}</p><p className="text-sm text-ace-muted">{s.body}</p></div>
            </div>
          ))}
        </div>

        <div className="mb-8 grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4 text-sm">
            <p className="mb-2 flex items-center gap-1.5 font-medium text-emerald-800"><CheckCircle2 className="h-4 w-4" /> ScrapTrust can</p>
            <ul className="list-disc space-y-1 pl-5 text-emerald-900">
              <li>tell the battery type of black mass (NMC, LFP, LCO…)</li>
              <li>estimate nickel, cobalt, manganese and lithium from XRF readings</li>
              <li>read numbers from a photo of the gun screen</li>
              <li>compare bags, spot odd ones and suggest which to send to the lab</li>
              <li>identify scrap from a photo and give safety advice</li>
            </ul>
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4 text-sm">
            <p className="mb-2 flex items-center gap-1.5 font-medium text-amber-800"><XCircle className="h-4 w-4" /> ScrapTrust cannot</p>
            <ul className="list-disc space-y-1 pl-5 text-amber-900">
              <li>replace a lab test: every number is an estimate</li>
              <li>measure lithium directly (it is calculated)</li>
              <li>give prices or decide a deal for you</li>
              <li>be sure about unusual material it has not seen before</li>
            </ul>
          </div>
        </div>

        <div className="mb-8 flex gap-3 rounded-2xl border border-red-200 bg-red-50/60 p-4 text-sm text-red-900">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <p><strong>Safety:</strong> damaged, swollen or hot lithium batteries can catch fire. Never crush or puncture them, keep them apart from other waste, and follow your site's fire and handling rules.</p>
        </div>

        <h2 className="mb-3 text-lg font-medium">Common questions</h2>
        <div className="mb-8 space-y-2">
          {FAQ.map(([q, a]) => (
            <details key={q} className="rounded-xl border border-ace-line bg-white/70 px-4 py-3 text-sm">
              <summary className="cursor-pointer font-medium">{q}</summary>
              <p className="mt-2 text-ace-muted">{a}</p>
            </details>
          ))}
        </div>

        <div className="mb-4 flex gap-3 rounded-2xl border border-ace-line bg-white/70 p-4 text-sm">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-ace-terracotta" />
          <p><strong>Your data:</strong> your messages, files and results are saved in your Library and kept by ACE Green to check quality and to improve ScrapTrust over time. Only you see your Library; administrators can see activity records. Please don't upload personal information such as ID documents.</p>
        </div>
        <div className="flex gap-3 rounded-2xl border border-ace-line bg-white/70 p-4 text-sm">
          <Mail className="mt-0.5 h-5 w-5 shrink-0 text-ace-terracotta" />
          <p><strong>Need a person?</strong> {contact ? <>Contact <span className="font-medium">{contact}</span>.</> : 'Contact your ScrapTrust administrator or your site supervisor.'}</p>
        </div>
      </div>
    </div>
  );
}
