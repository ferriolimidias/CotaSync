import { useMemo, useState } from "react";
import { Check, ChevronsUpDown, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export type SearchableSelectOption = { value: string; label: string; description?: string };

type SearchableSelectProps = {
  value: string;
  options: SearchableSelectOption[];
  onValueChange: (value: string) => void;
  placeholder: string;
  emptyLabel?: string;
  disabled?: boolean;
  className?: string;
};

export function SearchableSelect({
  value,
  options,
  onValueChange,
  placeholder,
  emptyLabel = "Nenhum resultado encontrado.",
  disabled = false,
  className,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const selected = useMemo(() => options.find((option) => option.value === value), [options, value]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label={placeholder}
          disabled={disabled}
          className={`w-full justify-between font-normal ${className || ""}`}
        >
          <span className="flex min-w-0 items-center gap-2 truncate">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{selected?.label || placeholder}</span>
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[--radix-popover-trigger-width] p-0">
        <Command>
          <CommandInput autoFocus placeholder={`Buscar ${placeholder.toLowerCase()}...`} />
          <CommandList>
            <CommandEmpty>{emptyLabel}</CommandEmpty>
            {options.map((option) => (
              <CommandItem
                key={option.value}
                value={`${option.label} ${option.description || ""}`}
                onSelect={() => {
                  onValueChange(option.value);
                  setOpen(false);
                }}
                className="items-start gap-2 py-2.5"
              >
                <Check className={`mt-0.5 h-4 w-4 shrink-0 ${value === option.value ? "opacity-100" : "opacity-0"}`} />
                <span className="min-w-0">
                  <span className="block truncate">{option.label}</span>
                  {option.description && <span className="block truncate text-xs text-muted-foreground">{option.description}</span>}
                </span>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
