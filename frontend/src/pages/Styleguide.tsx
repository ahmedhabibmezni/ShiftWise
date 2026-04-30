import { useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Cpu,
  Database,
  HardDrive,
  Plus,
  Server,
} from "lucide-react";
import { Sidebar } from "@/components/shell/Sidebar";
import { Header } from "@/components/shell/Header";
import { Footer } from "@/components/shell/Footer";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Checkbox } from "@/components/ui/Checkbox";
import { Badge } from "@/components/ui/Badge";
import { KPIPrimary } from "@/components/ui/KPIPrimary";
import { KPISecondary } from "@/components/ui/KPISecondary";
import { StatBlock } from "@/components/ui/StatBlock";
import { MiniRow } from "@/components/ui/MiniRow";
import { AlertRow } from "@/components/ui/AlertRow";
import { Table, THead, TR, TH, TD } from "@/components/ui/Table";
import { SlideOver } from "@/components/ui/SlideOver";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { TopProgress } from "@/components/ui/TopProgress";
import { Tabs } from "@/components/ui/Tabs";
import { Icon } from "@/components/ui/Icon";

const TOKEN_GROUPS: { title: string; tokens: [string, string][] }[] = [
  {
    title: "surfaces",
    tokens: [
      ["bg", "var(--bg)"],
      ["bg-elev", "var(--bg-elev)"],
      ["bg-elev-2", "var(--bg-elev-2)"],
    ],
  },
  {
    title: "ink + lines",
    tokens: [
      ["ink", "var(--ink)"],
      ["ink-muted", "var(--ink-muted)"],
      ["line", "var(--line)"],
      ["line-strong", "var(--line-strong)"],
    ],
  },
  {
    title: "semantic",
    tokens: [
      ["signal", "var(--signal)"],
      ["info", "var(--info)"],
      ["ok", "var(--ok)"],
      ["warn", "var(--warn)"],
      ["err", "var(--err)"],
    ],
  },
];

const MIGRATIONS = [
  { source: "LYO-HV-02", target: "PAR-HV-01", vmId: "vm-312", pct: 68, size: "2.1 TB", duration: "2m 14s" },
  { source: "LON-HV-01", target: "LON-HV-02", vmId: "vm-198", pct: 41, size: "980 GB", duration: "4m 08s" },
  { source: "PAR-HV-02", target: "PAR-HV-01", vmId: "vm-256", pct: 22, size: "1.2 TB", duration: "6m 51s" },
  { source: "LYO-HV-01", target: "LYO-HV-02", vmId: "vm-172", pct: 12, size: "320 GB", duration: "9m 33s" },
];

const ALERTS: { time: string; message: string; severity: "critical" | "high" | "medium" | "low" }[] = [
  { time: "14:21", message: "ha storage latency > 200ms on PAR-HV-02", severity: "critical" },
  { time: "14:19", message: "migration stuck > 10m on vm-198", severity: "high" },
  { time: "14:18", message: "cpu usage > 85% on LYO-HV-01", severity: "medium" },
  { time: "14:12", message: "backup delayed on 2 nodes", severity: "low" },
  { time: "14:07", message: "certificate expires in 7 days (3)", severity: "low" },
];

const QUEUE = [
  { pos: "01", src: "LYO-HV-01", dst: "LYO-HV-02", vm: "vm-442", size: "1.8 TB", added: "14:21:58" },
  { pos: "02", src: "PAR-HV-02", dst: "PAR-HV-01", vm: "vm-309", size: "980 GB", added: "14:21:43" },
  { pos: "03", src: "LON-HV-01", dst: "LON-HV-02", vm: "vm-201", size: "320 GB", added: "14:21:31" },
  { pos: "04", src: "PAR-HV-01", dst: "PAR-HV-02", vm: "vm-118", size: "256 GB", added: "14:21:02" },
  { pos: "05", src: "LYO-HV-02", dst: "LYO-HV-01", vm: "vm-531", size: "1.2 TB", added: "14:20:47" },
];

const TYPE_SAMPLES: { token: string; cls: string; mono?: boolean; sample: string }[] = [
  { token: "display", cls: "text-display", sample: "23" },
  { token: "major", cls: "text-major", sample: "1.289" },
  { token: "h1", cls: "text-h1 lowercase", sample: "overview" },
  { token: "h2", cls: "text-h2 lowercase", sample: "tout est opérationnel" },
  { token: "h3", cls: "text-h3 lowercase", sample: "migrations en cours" },
  { token: "body", cls: "text-body", sample: "Le cluster fonctionne nominalement." },
  { token: "meta", cls: "text-meta text-ink-muted", sample: "il y a 14 minutes" },
  { token: "mono-lg", cls: "text-mono-lg font-mono tabular", mono: true, sample: "1,234,567" },
  { token: "mono", cls: "text-mono font-mono tabular", mono: true, sample: "vm-312 · 14:22:01 · 2.1 TB" },
  { token: "mono-sm", cls: "text-mono-sm font-mono uppercase", mono: true, sample: "MIG-7F3A · COMPATIBLE" },
];

export default function Styleguide() {
  const [open, setOpen] = useState(false);
  const [topActive, setTopActive] = useState(false);

  return (
    <div className="min-h-screen bg-bg text-ink flex flex-col">
      <TopProgress active={topActive} />
      <div className="flex flex-1 min-h-0">
        <Sidebar active="overview" />

        <div className="flex-1 flex flex-col min-w-0">
          <Header title="overview" />

          <main className="flex-1 overflow-auto">
            <div className="max-w-[1440px] mx-auto p-8 space-y-12">
              {/* DASHBOARD HERO --------------------------------------------------- */}
              <section className="grid gap-6 grid-cols-12">
                <div className="col-span-12 lg:col-span-7">
                  <KPIPrimary
                    label="migrations en cours"
                    value="23"
                    tone="signal"
                    cta="voir toutes les migrations"
                    onCta={() => setTopActive((v) => !v)}
                  >
                    <div>
                      {MIGRATIONS.map((m) => (
                        <MiniRow key={m.vmId} {...m} />
                      ))}
                    </div>
                  </KPIPrimary>
                </div>
                <div className="col-span-12 lg:col-span-5 grid grid-cols-1 sm:grid-cols-3 gap-4 lg:grid-cols-1 xl:grid-cols-3 content-start">
                  <KPISecondary
                    label="hyperviseurs actifs"
                    value="07"
                    suffix="/ 12"
                    delta={{ dir: "up", value: "↑ 2", tone: "ok" }}
                  />
                  <KPISecondary
                    label="machines virtuelles"
                    value="1.289"
                    delta={{ dir: "up", value: "↑ 93", tone: "ok" }}
                  />
                  <KPISecondary
                    label="disponibilité globale"
                    value="93.6%"
                    delta={{ dir: "down", value: "↓ 0.4%", tone: "err" }}
                  />
                </div>
              </section>

              {/* INFRASTRUCTURE BLOCK --------------------------------------------- */}
              <section>
                <KPIPrimary
                  label="infrastructure"
                  tone="info"
                  headline="tout est opérationnel"
                  cta="voir détails"
                >
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-8 mt-2">
                    <StatBlock
                      icon={Cpu}
                      label="cpu moyen"
                      value="31%"
                      delta={{ dir: "down", value: "↓ 4%", tone: "ok" }}
                    />
                    <StatBlock
                      icon={Database}
                      label="mémoire utilisée"
                      value="46%"
                      delta={{ dir: "down", value: "↓ 3%", tone: "ok" }}
                    />
                    <StatBlock
                      icon={HardDrive}
                      label="stockage libre"
                      value="1.2 TB"
                      delta={{ dir: "up", value: "↑ 120 GB", tone: "ok" }}
                    />
                  </div>
                </KPIPrimary>
              </section>

              {/* ALERTS + QUEUE --------------------------------------------------- */}
              <section className="grid gap-6 grid-cols-12">
                <div className="col-span-12 lg:col-span-5 border border-line bg-bg-elev">
                  <div className="h-12 px-4 flex items-center justify-between border-b border-line">
                    <div className="flex items-center gap-3">
                      <h2 className="text-h3 lowercase">alerts</h2>
                      <span className="inline-flex items-center justify-center min-w-[22px] h-5 px-1.5 rounded-full bg-signal text-signal-ink font-mono text-[11px] font-medium tabular">
                        12
                      </span>
                    </div>
                    <Button variant="ghost" trailingIcon={<Icon icon={ArrowRight} size={16} />}>
                      voir tout
                    </Button>
                  </div>
                  <div>
                    {ALERTS.map((a) => (
                      <AlertRow key={a.time + a.message} {...a} />
                    ))}
                  </div>
                </div>

                <div className="col-span-12 lg:col-span-7 border border-line bg-bg-elev">
                  <div className="h-12 px-4 flex items-center justify-between border-b border-line">
                    <div className="flex items-center gap-3">
                      <h2 className="text-h3 lowercase">migration queue</h2>
                      <span className="inline-flex items-center justify-center min-w-[22px] h-5 px-1.5 rounded-full bg-bg-elev-2 text-ink font-mono text-[11px] font-medium tabular border border-line-strong">
                        8
                      </span>
                    </div>
                    <Button variant="ghost" trailingIcon={<Icon icon={ArrowRight} size={16} />}>
                      voir la queue
                    </Button>
                  </div>
                  <Table className="border-0">
                    <THead>
                      <TR>
                        <TH>position</TH>
                        <TH>source</TH>
                        <TH>cible</TH>
                        <TH>vm</TH>
                        <TH numeric>taille</TH>
                        <TH numeric>ajouté</TH>
                        <TH>statut</TH>
                      </TR>
                    </THead>
                    <tbody>
                      {QUEUE.map((q) => (
                        <TR key={q.pos} interactive>
                          <TD mono muted>{q.pos}</TD>
                          <TD mono>{q.src}</TD>
                          <TD mono>{q.dst}</TD>
                          <TD mono>{q.vm}</TD>
                          <TD numeric>{q.size}</TD>
                          <TD numeric muted>{q.added}</TD>
                          <TD>
                            <span className="font-mono text-[12px] uppercase text-signal tabular">
                              en attente
                            </span>
                          </TD>
                        </TR>
                      ))}
                    </tbody>
                  </Table>
                </div>
              </section>

              {/* TOKENS ---------------------------------------------------------- */}
              <Section label="tokens">
                <div className="grid gap-8 md:grid-cols-3">
                  {TOKEN_GROUPS.map((g) => (
                    <div key={g.title}>
                      <div className="font-mono text-[11px] uppercase text-ink-muted mb-2">
                        {g.title}
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {g.tokens.map(([name, val]) => (
                          <div key={name} className="border border-line">
                            <div className="h-16" style={{ background: val }} />
                            <div className="px-2 py-1.5">
                              <div className="font-mono text-[11px] text-ink">{name}</div>
                              <div className="font-mono text-[10px] text-ink-muted truncate">
                                {val}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </Section>

              {/* TYPE ------------------------------------------------------------ */}
              <Section label="typography">
                <div className="border border-line divide-y divide-line">
                  {TYPE_SAMPLES.map((t) => (
                    <div
                      key={t.token}
                      className="grid grid-cols-[120px_1fr] gap-6 items-baseline px-4 py-3"
                    >
                      <div className="font-mono text-[11px] uppercase text-ink-muted">
                        {t.token}
                      </div>
                      <div className={t.cls}>{t.sample}</div>
                    </div>
                  ))}
                </div>
              </Section>

              {/* BUTTONS --------------------------------------------------------- */}
              <Section label="buttons">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <ButtonRow label="primary" variant="primary" />
                  <ButtonRow label="secondary" variant="secondary" />
                  <ButtonRow label="danger" variant="danger" />
                  <ButtonRow label="ghost" variant="ghost" />
                </div>
                <div className="mt-4 flex items-center gap-3">
                  <span className="font-mono text-[11px] uppercase text-ink-muted w-24">
                    icon-only
                  </span>
                  <IconButton aria-label="Ajouter" variant="primary">
                    <Icon icon={Plus} size={20} />
                  </IconButton>
                  <IconButton aria-label="Serveur">
                    <Icon icon={Server} size={20} />
                  </IconButton>
                  <IconButton aria-label="Alerte">
                    <Icon icon={AlertTriangle} size={20} />
                  </IconButton>
                </div>
              </Section>

              {/* INPUTS ---------------------------------------------------------- */}
              <Section label="inputs">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl">
                  <Field label="hyperviseur — nom">
                    <Input placeholder="vsphere-prod-01" />
                  </Field>
                  <Field label="environnement">
                    <Select defaultValue="prod">
                      <option value="prod">production</option>
                      <option value="staging">staging</option>
                      <option value="lab">lab</option>
                    </Select>
                  </Field>
                  <Field label="adresse — invalide">
                    <Input invalid defaultValue="10.9.21." />
                    <FieldError>adresse ip incomplète.</FieldError>
                  </Field>
                  <Field label="désactivé">
                    <Input disabled placeholder="lecture seule" />
                  </Field>
                  <Field label="description" className="md:col-span-2">
                    <Textarea placeholder="Note interne pour l'équipe ops…" />
                  </Field>
                  <Field label="options">
                    <label className="inline-flex items-center gap-2 text-[14px]">
                      <Checkbox defaultChecked /> activer la découverte automatique
                    </label>
                  </Field>
                </div>
              </Section>

              {/* BADGES ---------------------------------------------------------- */}
              <Section label="badges">
                <div className="space-y-3">
                  <Row label="compatibilité">
                    <Badge variant="ok">compatible</Badge>
                    <Badge variant="partial">partial</Badge>
                    <Badge variant="incompatible">incompatible</Badge>
                    <Badge variant="info">info</Badge>
                    <Badge variant="neutral">unknown</Badge>
                  </Row>
                  <Row label="severity">
                    <Badge variant="critical" dot={false}>critical</Badge>
                    <Badge variant="high" dot={false}>high</Badge>
                    <Badge variant="medium" dot={false}>medium</Badge>
                    <Badge variant="low" dot={false}>low</Badge>
                  </Row>
                </div>
              </Section>

              {/* PROGRESS / LIVE / TOP ------------------------------------------- */}
              <Section label="progress · live · top-bar">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl">
                  <div className="border border-line bg-bg-elev p-6 space-y-4">
                    <div className="font-mono text-[11px] uppercase text-ink-muted">
                      progress bar
                    </div>
                    <ProgressBar value={68} showPct />
                    <ProgressBar value={94} showPct variant="ok" />
                    <ProgressBar value={22} showPct />
                  </div>
                  <div className="border border-line bg-bg-elev p-6 space-y-4">
                    <div className="font-mono text-[11px] uppercase text-ink-muted">
                      live + top bar
                    </div>
                    <div className="flex items-center gap-3">
                      <LiveIndicator />
                      <span className="text-[14px]">migration mig-7f3a en cours…</span>
                    </div>
                    <Button variant="secondary" onClick={() => setTopActive((v) => !v)}>
                      {topActive ? "arrêter top-bar" : "démarrer top-bar"}
                    </Button>
                  </div>
                </div>
              </Section>

              {/* SLIDE OVER ------------------------------------------------------ */}
              <Section label="slide-over (480px)">
                <Button variant="primary" onClick={() => setOpen(true)}>
                  ouvrir le panneau
                </Button>
              </Section>

              {/* TABS ------------------------------------------------------------ */}
              <Section label="tabs">
                <div className="max-w-2xl">
                  <Tabs
                    tabs={[
                      {
                        id: "profil",
                        label: "profil",
                        content: (
                          <p className="text-[14px] text-ink-muted">
                            Informations utilisateur courantes — nom, rôle, fuseau, langue.
                          </p>
                        ),
                      },
                      {
                        id: "utilisateurs",
                        label: "utilisateurs",
                        content: (
                          <p className="text-[14px] text-ink-muted">
                            Gestion des utilisateurs (admin uniquement).
                          </p>
                        ),
                      },
                      {
                        id: "roles",
                        label: "rôles",
                        content: (
                          <p className="text-[14px] text-ink-muted">
                            Rôles système en lecture seule, rôles personnalisés modifiables.
                          </p>
                        ),
                      },
                    ]}
                  />
                </div>
              </Section>

              {/* ICONS ----------------------------------------------------------- */}
              <Section label="icons — lucide stroke 1.5 · 16/20">
                <div className="flex items-center gap-6">
                  {[Server, Database, Activity, AlertTriangle, Plus].map((I, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Icon icon={I} size={16} />
                      <Icon icon={I} size={20} />
                    </div>
                  ))}
                </div>
              </Section>
            </div>
          </main>

          <Footer />
        </div>
      </div>

      {/* Persistent CTA — bottom right */}
      <div className="fixed bottom-6 right-6 z-30">
        <Button
          variant="primary"
          leadingIcon={<Icon icon={Plus} size={20} />}
          trailingIcon={<Icon icon={ArrowRight} size={20} />}
          className="h-12 px-6"
        >
          nouvelle migration
        </Button>
      </div>

      <SlideOver
        open={open}
        onClose={() => setOpen(false)}
        title="détails — vsphere-prod-01"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              annuler
            </Button>
            <Button variant="primary">enregistrer</Button>
          </>
        }
      >
        <dl className="grid grid-cols-[140px_1fr] gap-y-3 text-[14px]">
          <dt className="font-mono text-[11px] uppercase text-ink-muted">host</dt>
          <dd className="font-mono tabular">10.9.21.151</dd>
          <dt className="font-mono text-[11px] uppercase text-ink-muted">type</dt>
          <dd className="font-mono uppercase">vsphere</dd>
          <dt className="font-mono text-[11px] uppercase text-ink-muted">vms</dt>
          <dd className="font-mono tabular">247</dd>
          <dt className="font-mono text-[11px] uppercase text-ink-muted">ram</dt>
          <dd className="font-mono tabular">1,024.0 GB</dd>
          <dt className="font-mono text-[11px] uppercase text-ink-muted">statut</dt>
          <dd>
            <Badge variant="ok">active</Badge>
          </dd>
          <dt className="font-mono text-[11px] uppercase text-ink-muted">dernière sync</dt>
          <dd className="font-mono tabular">14:21:03 UTC</dd>
        </dl>
        <div className="h-px bg-line my-6" />
        <p className="text-[13px] text-ink-muted">
          Le panneau coulisse depuis la droite en 200ms. Esc ferme. Le backdrop
          est solide, sans flou.
        </p>
      </SlideOver>
    </div>
  );
}

// helpers --------------------------------------------------------------------

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="font-mono text-[11px] uppercase tracking-[0.04em] text-ink-muted border-b border-line pb-2 mb-4">
        {label}
      </h2>
      {children}
    </section>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className ?? ""}`}>
      <span className="font-mono text-[11px] uppercase tracking-[0.04em] text-ink-muted block mb-2">
        {label}
      </span>
      {children}
    </label>
  );
}

function FieldError({ children }: { children: React.ReactNode }) {
  return (
    <span className="block mt-1.5 font-mono text-[12px] text-err">{children}</span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-4">
      <span className="font-mono text-[11px] uppercase text-ink-muted w-32">
        {label}
      </span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function ButtonRow({
  label,
  variant,
}: {
  label: string;
  variant: "primary" | "secondary" | "danger" | "ghost";
}) {
  return (
    <div className="border border-line p-4 space-y-3">
      <div className="font-mono text-[11px] uppercase text-ink-muted">{label}</div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant={variant}>action</Button>
        <Button variant={variant} disabled>
          disabled
        </Button>
        <Button variant={variant} loading>
          loading
        </Button>
        <Button variant={variant} uppercase>
          UPPERCASE
        </Button>
      </div>
    </div>
  );
}
