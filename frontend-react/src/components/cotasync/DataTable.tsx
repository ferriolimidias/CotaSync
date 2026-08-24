import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export type Column<T> = {
  key: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  className?: string;
};

export function DataTable<T extends { id: string }>({
  columns,
  data,
  empty,
}: {
  columns: Column<T>[];
  data: T[];
  empty?: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40 hover:bg-muted/40">
            {columns.map((c) => (
              <TableHead key={c.key} className={c.className}>
                {c.header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="h-32 text-center text-muted-foreground">
                {empty ?? "Sem dados para exibir."}
              </TableCell>
            </TableRow>
          ) : (
            data.map((row) => (
              <TableRow key={row.id}>
                {columns.map((c) => (
                  <TableCell key={c.key} className={c.className}>
                    {c.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
