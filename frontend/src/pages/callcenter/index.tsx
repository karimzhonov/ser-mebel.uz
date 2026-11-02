import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Columns3, List, ListTodo, Plus } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { Button, Chip, PageHeader, SearchInput, Segmented, Select } from "@/components/ui";
import { useUrlState } from "@/lib/useUrlState";
import { LeadBoard } from "./LeadBoard";
import { LeadCreateModal } from "./LeadCreateModal";
import { LeadDetailModal } from "./LeadDetailModal";
import { LeadList } from "./LeadList";
import { useAssignees, useLeadSources } from "./shared";

export default function CallCenterPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const sources = useLeadSources();
  const assignees = useAssignees();
  const { state, page, set } = useUrlState({
    view: "board",
    search: "",
    assigned_to: "",
    source: "",
    solution: "",
    date_from: "",
    date_to: "",
  });
  const [creating, setCreating] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const openId = searchParams.get("open");
  const open = (id: number) => setSearchParams((p) => (p.set("open", String(id)), p));

  const filters = { search: state.search, assigned_to: state.assigned_to, source: state.source };
  const selectedSources = state.source.split(",").filter(Boolean);
  const toggleSource = (key: string) =>
    set({
      source: (selectedSources.includes(key) ? selectedSources.filter((s) => s !== key) : [...selectedSources, key]).join(","),
    });

  return (
    <div>
      <PageHeader
        title="Call-center"
        subtitle="Mijozlar arizalari, qo'ng'iroqlar va keyingi qadamlar"
        actions={
          <>
            <Button variant="outline" icon={<ListTodo className="h-4 w-4" />} onClick={() => navigate("/call-center/tasks")}>
              Bugungi ishlarim
            </Button>
            {can("call_center.add_invoice") && (
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                Yangi ariza
              </Button>
            )}
          </>
        }
      />

      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <Segmented
          value={state.view as "board" | "list"}
          onChange={(view) => set({ view })}
          options={[
            { value: "board", label: <span className="flex items-center gap-1.5"><Columns3 className="h-4 w-4" /> Doska</span> },
            { value: "list", label: <span className="flex items-center gap-1.5"><List className="h-4 w-4" /> Ro'yxat</span> },
          ]}
        />
        <SearchInput className="flex-1" value={state.search} onChange={(v) => set({ search: v })} placeholder="F.I.Sh., telefon, izoh" />
        <Select className="lg:w-56" value={state.assigned_to} onChange={(e) => set({ assigned_to: e.target.value })}>
          <option value="">Mas'ul: hammasi</option>
          <option value="me">Mening mijozlarim</option>
          <option value="none">Mas'ulsiz</option>
          {assignees.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
      </div>

      {sources.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="muted text-xs">Manba:</span>
          <Chip active={!selectedSources.length} onClick={() => set({ source: "" })}>
            Hammasi
          </Chip>
          {sources.map((s) => (
            <Chip key={s.value} active={selectedSources.includes(s.value)} onClick={() => toggleSource(s.value)}>
              {s.label}
            </Chip>
          ))}
        </div>
      )}

      {state.view === "list" ? (
        <LeadList
          filters={filters}
          solution={state.solution}
          dateFrom={state.date_from}
          dateTo={state.date_to}
          page={page}
          set={set}
          onOpen={open}
        />
      ) : (
        <LeadBoard filters={filters} onOpen={open} />
      )}

      {creating && <LeadCreateModal onClose={() => setCreating(false)} onCreated={(inv) => inv?.id && open(inv.id)} />}
      {openId && <LeadDetailModal id={Number(openId)} onClose={() => setSearchParams((p) => (p.delete("open"), p))} />}
    </div>
  );
}
