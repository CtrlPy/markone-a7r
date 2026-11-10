// Decompile every function that references one of the given ELF virtual addresses (image base added),
// e.g. a global or the GOT entry that points to it.
// Usage: -postScript DecompileRefsTo.java <outfile> <vaddr_hex>...
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.*;
import java.util.*;

public class DecompileRefsTo extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(args[0]));
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Set<Function> seen = new LinkedHashSet<>();
        for (int i = 1; i < args.length; i++) {
            long v = Long.parseLong(args[i].replace("0x", ""), 16);
            Address a = currentProgram.getImageBase().add(v);
            for (Reference r : getReferencesTo(a)) {
                Function c = getFunctionContaining(r.getFromAddress());
                out.println("// ref to " + a + " from " + r.getFromAddress() + " (" + r.getReferenceType() + ") in "
                        + (c == null ? "?" : c.getName(true)));
                if (c != null) seen.add(c);
            }
        }
        for (Function f : seen) {
            out.println("\n// ===== " + f.getName(true) + " @ " + f.getEntryPoint());
            DecompileResults res = dec.decompileFunction(f, 120, monitor);
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// failed " + res.getErrorMessage());
        }
        out.close();
    }
}
