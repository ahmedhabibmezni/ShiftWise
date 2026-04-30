import { useState } from "react";
import { Activity, Database, Server } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Checkbox } from "@/components/ui/Checkbox";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { Table, THead, TR, TH, TD } from "@/components/ui/Table";
import { SlideOver } from "@/components/ui/SlideOver";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { TopProgress } from "@/components/ui/TopProgress";
import { Tabs } from "@/components/ui/Tabs";
import { Icon } from "@/components/ui/Icon";
import { Header } from "@/components/shell/Header";

const TOKENS = [
  ["bg", "var(--bg)"],
  ["bg-elev", "var(--bg-elev)"],
  ["ink", "var(--ink)"],
  ["ink-muted", "var(--ink-muted)"],
  ["line", "var(--line)"],
  ["line-soft", "var(--line-soft)"],
  ["signal", "var(--signal)"],
  ["info", "var(--info)"],
  ["ok", "var(--ok)"],
  ["warn", "var(--warn)"],
  ["err", "var(--err)"],
];

const TYPE_SCALE = [11, 12, 13, 14, 16, 20, 28];

export default function Styleguide() {
  const [open, setOpen] = useState(false);
  const [topActive, setTopActive] = useState(false);
  const [progress, setProgress] = useState(42);

  return (
    <div className="min-h-screen bg-bg text-ink">
      <TopProgress active={topActive} />
      <Header />

      <main className="max-w-[1440px] mx-auto px-6 py-8 space-y-12">
        <section>
          <SectionLabel>STYLEGUIDE — DESIGN SYSTEM v1</SectionLabel>
          <p className="text-ink-muted text-[13px] mt-2 max-w-2xl">
            Restraint. Density. Borders, not shadows. Mono for numbers. Single
            accent (signal). Toggle the theme in the header to verify both modes.
          </p>
        </section>

        {/* Tokens ---------------------------------------------------------- */}
        <section>
          <SectionLabel>TOKENS</SectionLabel>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 mt-3">
            {TOKENS.map(([name, val]) => (
              <div key={name} className="border border-line">
                <div
                  className="h-12 border-b border-line"
                  style={{ background: val }}
                />
                <div className="px-2 py-1.5 flex items-center justify-between">
                  <span className="font-mono text-[11px] text-ink">{name}</span>
                  <span className="font-mono text-[11px] text-ink-muted tabular-nums">
                    {val}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Type scale ------------------------------------------------------ */}
        <section>
          <SectionLabel>TYPE</SectionLabel>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-3">
            <div className="border border-line p-4 space-y-2">
              <div className="font-mono text-[11px] uppercase text-ink-muted">
                Sans — Inter Tight
              </div>
              {TYPE_SCALE.map((s) => (
                <div key={s} className="flex items-baseline gap-3">
                  <span className="font-mono text-[11px] text-ink-muted tabular-nums w-8">
                    {s}px
                  </span>
                  <span style={{ fontSize: `${s}px` }}>Migration en cours</span>
                </div>
              ))}
            </div>
            <div className="border border-line p-4 space-y-2">
              <div className="font-mono text-[11px] uppercase text-ink-muted">
                Mono — JetBrains Mono · tabular-nums
              </div>
              {TYPE_SCALE.map((s) => (
                <div key={s} className="flex items-baseline gap-3">
                  <span className="font-mono text-[11px] text-ink-muted tabular-nums w-8">
                    {s}px
                  </span>
                  <span
                    className="font-mono tabular-nums"
                    style={{ fontSize: `${s}px` }}
                  >
                    1,234,567 · 99.4%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Buttons --------------------------------------------------------- */}
        <section>
          <SectionLabel>BUTTONS</SectionLabel>
          <div className="grid grid-cols-3 gap-3 mt-3 max-w-3xl">
            <ButtonRow label="primary" variant="primary" />
            <ButtonRow label="secondary" variant="secondary" />
            <ButtonRow label="danger" variant="danger" />
          </div>
        </section>

        {/* Inputs ---------------------------------------------------------- */}
        <section>
          <SectionLabel>INPUTS</SectionLabel>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3 max-w-3xl">
            <Field label="DEFAULT">
              <Input placeholder="vsphere-prod-01" />
            </Field>
            <Field label="FOCUSED — TAB INTO IT">
              <Input placeholder="cliquez ou tab" />
            </Field>
            <Field label="DISABLED">
              <Input placeholder="non-modifiable" disabled />
            </Field>
            <Field label="INVALID">
              <Input invalid defaultValue="bad-value" />
              <FieldError>Le champ est requis.</FieldError>
            </Field>
            <Field label="SELECT">
              <Select defaultValue="vsphere">
                <option value="vsphere">vSphere</option>
                <option value="kvm">KVM</option>
                <option value="hyperv">Hyper-V</option>
              </Select>
            </Field>
            <Field label="TEXTAREA">
              <Textarea placeholder="Description courte…" />
            </Field>
            <Field label="CHECKBOX">
              <label className="inline-flex items-center gap-2 text-[13px]">
                <Checkbox defaultChecked /> Activer la découverte automatique
              </label>
            </Field>
          </div>
        </section>

        {/* Badges ---------------------------------------------------------- */}
        <section>
          <SectionLabel>STATUS BADGES</SectionLabel>
          <div className="flex flex-wrap items-center gap-2 mt-3">
            <Badge variant="ok">COMPATIBLE</Badge>
            <Badge variant="partial">PARTIAL</Badge>
            <Badge variant="incompatible">INCOMPATIBLE</Badge>
            <Badge variant="info">INFO</Badge>
            <Badge variant="warn">WARN</Badge>
            <Badge variant="neutral">UNKNOWN</Badge>
          </div>
        </section>

        {/* Panel ----------------------------------------------------------- */}
        <section>
          <SectionLabel>PANEL</SectionLabel>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
            <Panel label="MIGRATION QUEUE — 03 ACTIVE" meta="UPDATED 14:22:01">
              <p className="text-[13px] text-ink-muted">
                Panneaux SCADA — coin haut-gauche réservé au libellé en mono
                majuscules.
              </p>
            </Panel>
            <Panel label="HYPERVISORS" meta="07 / 12">
              <div className="grid grid-cols-3 gap-2 text-center">
                <KPI value="07" label="ACTIVE" />
                <KPI value="03" label="UNREACHABLE" />
                <KPI value="02" label="INACTIVE" />
              </div>
            </Panel>
          </div>
        </section>

        {/* Table ----------------------------------------------------------- */}
        <section>
          <SectionLabel>TABLE — DENSE 32PX ROWS</SectionLabel>
          <div className="mt-3">
            <Table>
              <THead>
                <TR>
                  <TH>NAME</TH>
                  <TH>TYPE</TH>
                  <TH>STATUS</TH>
                  <TH numeric>VMS</TH>
                  <TH numeric>RAM (GB)</TH>
                </TR>
              </THead>
              <tbody>
                <TR interactive>
                  <TD>vsphere-prod-01</TD>
                  <TD mono>VSPHERE</TD>
                  <TD>
                    <Badge variant="ok">ACTIVE</Badge>
                  </TD>
                  <TD numeric>247</TD>
                  <TD numeric>1,024.0</TD>
                </TR>
                <TR interactive>
                  <TD>kvm-lab-02</TD>
                  <TD mono>KVM</TD>
                  <TD>
                    <Badge variant="warn">UNREACHABLE</Badge>
                  </TD>
                  <TD numeric>32</TD>
                  <TD numeric>128.0</TD>
                </TR>
                <TR interactive>
                  <TD>hyperv-edge-03</TD>
                  <TD mono>HYPER_V</TD>
                  <TD>
                    <Badge variant="incompatible">ERROR</Badge>
                  </TD>
                  <TD numeric>8</TD>
                  <TD numeric>32.0</TD>
                </TR>
              </tbody>
            </Table>
          </div>
        </section>

        {/* Progress + live ------------------------------------------------- */}
        <section>
          <SectionLabel>PROGRESS · LIVE INDICATOR · TOP BAR</SectionLabel>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-3">
            <Panel label="PROGRESS BAR (4PX)">
              <ProgressBar value={progress} showPct className="mb-3" />
              <div className="flex items-center gap-2">
                <Button onClick={() => setProgress((p) => Math.max(0, p - 10))}>
                  -10
                </Button>
                <Button onClick={() => setProgress((p) => Math.min(100, p + 10))}>
                  +10
                </Button>
                <Button variant="primary" onClick={() => setProgress(0)}>
                  RESET
                </Button>
              </div>
            </Panel>

            <Panel label="LIVE + TOP PROGRESS">
              <div className="flex items-center gap-3 text-[13px] mb-3">
                <LiveIndicator />
                <span>Migration mig-7f3a en cours…</span>
              </div>
              <Button onClick={() => setTopActive((v) => !v)}>
                {topActive ? "ARRÊTER TOP-BAR" : "DÉMARRER TOP-BAR"}
              </Button>
            </Panel>
          </div>
        </section>

        {/* SlideOver ------------------------------------------------------- */}
        <section>
          <SectionLabel>SLIDE-OVER (480PX)</SectionLabel>
          <div className="mt-3">
            <Button variant="primary" onClick={() => setOpen(true)}>
              OUVRIR LE PANNEAU
            </Button>
          </div>
        </section>

        {/* Tabs ------------------------------------------------------------ */}
        <section>
          <SectionLabel>TABS</SectionLabel>
          <div className="mt-3 max-w-2xl">
            <Tabs
              tabs={[
                {
                  id: "profile",
                  label: "PROFIL",
                  content: (
                    <p className="text-[13px] text-ink-muted">
                      Onglet profil — informations utilisateur courantes.
                    </p>
                  ),
                },
                {
                  id: "users",
                  label: "UTILISATEURS",
                  content: (
                    <p className="text-[13px] text-ink-muted">
                      Onglet gestion des utilisateurs (admin uniquement).
                    </p>
                  ),
                },
                {
                  id: "roles",
                  label: "RÔLES",
                  content: (
                    <p className="text-[13px] text-ink-muted">
                      Rôles système en lecture seule, rôles personnalisés
                      modifiables.
                    </p>
                  ),
                },
              ]}
            />
          </div>
        </section>

        {/* Icons ----------------------------------------------------------- */}
        <section>
          <SectionLabel>ICONS — LUCIDE 1.5 STROKE · 16/20</SectionLabel>
          <div className="mt-3 flex items-center gap-4">
            <Icon icon={Server} size={16} />
            <Icon icon={Database} size={16} />
            <Icon icon={Activity} size={20} />
          </div>
        </section>
      </main>

      <SlideOver
        open={open}
        onClose={() => setOpen(false)}
        title="DÉTAILS — vsphere-prod-01"
        footer={
          <>
            <Button onClick={() => setOpen(false)}>ANNULER</Button>
            <Button variant="primary">ENREGISTRER</Button>
          </>
        }
      >
        <dl className="grid grid-cols-[120px_1fr] gap-y-2 text-[13px]">
          <dt className="font-mono text-[11px] uppercase text-ink-muted">HOST</dt>
          <dd className="font-mono">10.9.21.151</dd>
          <dt className="font-mono text-[11px] uppercase text-ink-muted">TYPE</dt>
          <dd className="font-mono">VSPHERE</dd>
          <dt className="font-mono text-[11px] uppercase text-ink-muted">VMS</dt>
          <dd className="font-mono tabular-nums">247</dd>
        </dl>
      </SlideOver>
    </div>
  );
}

// ---- helpers ---------------------------------------------------------------

function SectionLabel({ children }: { children: string }) {
  return (
    <h2 className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted border-b border-line pb-1">
      {children}
    </h2>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted block mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}

function FieldError({ children }: { children: React.ReactNode }) {
  return (
    <span className="block mt-1 font-mono text-[11px] text-err">{children}</span>
  );
}

function ButtonRow({
  label,
  variant,
}: {
  label: string;
  variant: "primary" | "secondary" | "danger";
}) {
  return (
    <div className="border border-line p-3 space-y-2">
      <div className="font-mono text-[11px] uppercase text-ink-muted">{label}</div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant={variant}>DEFAULT</Button>
        <Button variant={variant} disabled>
          DISABLED
        </Button>
        <Button variant={variant} loading>
          LOADING
        </Button>
      </div>
    </div>
  );
}

function KPI({ value, label }: { value: string; label: string }) {
  return (
    <div className="border border-line-soft p-2">
      <div className="font-mono tabular-nums text-[20px] text-ink">{value}</div>
      <div className="font-mono text-[11px] uppercase text-ink-muted">{label}</div>
    </div>
  );
}
