// Decompile functions that reference a defined string containing a pattern.
// Usage: -postScript DecompileStringRefs.java <pattern> <outfile>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.Reference;
import java.io.*;
import java.util.*;

public class DecompileStringRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[1]));
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Set<Function> fs = new LinkedHashSet<>();
        DataIterator it = currentProgram.getListing().getDefinedData(true);
        while (it.hasNext()) {
            Data d = it.next();
            if (!d.hasStringValue()) continue;
            String s = StringDataInstance.getStringDataInstance(d).getStringValue();
            if (s == null || !s.contains(a[0])) continue;
            out.println("// string @ " + d.getAddress() + ": " + s.trim());
            for (Reference r : getReferencesTo(d.getAddress())) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (f != null) fs.add(f);
            }
        }
        for (Function f : fs) {
            DecompileResults r = dec.decompileFunction(f, 120, monitor);
            out.println("\n// ===== " + f.getName(true) + " @ " + f.getEntryPoint());
            out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// failed");
        }
        out.close();
    }
}
