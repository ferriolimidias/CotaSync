import { useState } from "react";
import { Check, ChevronsUpDown, Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ApiClient } from "@/types/api";

type ClientSearchComboboxProps = {
  value: ApiClient | null;
  clients: ApiClient[];
  search: string;
  loading?: boolean;
  onSearchChange: (value: string) => void;
  onSelect: (client: ApiClient) => void;
  onClear: () => void;
};

export function ClientSearchCombobox({
  value,
  clients,
  search,
  loading = false,
  onSearchChange,
  onSelect,
  onClear,
}: ClientSearchComboboxProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="min-w-0 flex-1 justify-between font-normal"
          >
            <span className="flex min-w-0 items-center gap-2 truncate">
              <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{value?.name || "Buscar cliente..."}</span>
            </span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[--radix-popover-trigger-width] p-0">
          <Command shouldFilter={false}>
            <CommandInput
              autoFocus
              placeholder="Buscar cliente..."
              value={search}
              onValueChange={onSearchChange}
            />
            <CommandList>
              <CommandEmpty>{loading ? "Carregando clientes..." : "Nenhum cliente encontrado."}</CommandEmpty>
              {clients.map((client) => {
                const details = client.display_variables;
                return (
                  <CommandItem
                    key={client.id}
                    value={client.id}
                    onSelect={() => {
                      onSelect(client);
                      setOpen(false);
                    }}
                    className="items-start gap-3 py-2.5"
                  >
                    <Check
                      className={`mt-0.5 h-4 w-4 shrink-0 ${value?.id === client.id ? "opacity-100" : "opacity-0"}`}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{client.name}</span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                        Grupo {details.grupo || "-"} · Cota {details.cota || "-"} · Versão {details.versao || "-"}
                      </span>
                    </span>
                  </CommandItem>
                );
              })}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {value && (
        <Button type="button" variant="outline" size="icon" aria-label="Limpar cliente" onClick={onClear}>
          <X className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
