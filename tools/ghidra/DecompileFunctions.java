// Decompile functions at given ELF virtual addresses (image base added), plus their callers' names.
// Usage: -postScript DecompileFunctions.java <outfile> <vaddr_hex>...
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.*;

public class DecompileFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(args[0]));
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        for (int i = 1; i < args.length; i++) {
            long v = Long.parseLong(args[i].replace("0x", ""), 16);
            Address a = currentProgram.getImageBase().add(v);
            Function f = getFunctionContaining(a);
            if (f == null) { out.println("// no function at " + a); continue; }
            out.println("\n// ===== " + f.getName(true) + " @ " + f.getEntryPoint());
            for (Reference r : getReferencesTo(f.getEntryPoint())) {
                Function c = getFunctionContaining(r.getFromAddress());
                out.println("// called from " + (c == null ? r.getFromAddress().toString() : c.getName(true) + " @ " + r.getFromAddress()));
            }
            DecompileResults res = dec.decompileFunction(f, 120, monitor);
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// failed " + res.getErrorMessage());
        }
        out.close();
    }
}
