// Decompile every function that calls an imported/external function whose name contains a pattern.
// Usage (headless): -postScript DecompileCallers.java <pattern> <outfile>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DecompileCallers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String pattern = args[0];
        PrintWriter out = new PrintWriter(new FileWriter(args[1]));
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Set<Function> callers = new LinkedHashSet<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (!f.getName(true).contains(pattern)) continue;
            out.println("// target: " + f.getName(true) + " @ " + f.getEntryPoint());
            for (Reference r : getReferencesTo(f.getEntryPoint())) {
                Function c = getFunctionContaining(r.getFromAddress());
                if (c != null) callers.add(c);
            }
            for (Function thunk : f.getFunctionThunkAddresses() == null ? new Function[0] : new Function[0]) {}
        }
        // include callers of thunks
        Set<Function> extra = new LinkedHashSet<>();
        for (Function c : callers) {
            if (c.isThunk()) {
                for (Reference r : getReferencesTo(c.getEntryPoint())) {
                    Function cc = getFunctionContaining(r.getFromAddress());
                    if (cc != null) extra.add(cc);
                }
            }
        }
        callers.addAll(extra);
        for (Function c : callers) {
            if (c.isThunk()) continue;
            DecompileResults res = dec.decompileFunction(c, 120, monitor);
            out.println("\n// ===== " + c.getName(true) + " @ " + c.getEntryPoint());
            if (res.decompileCompleted()) out.println(res.getDecompiledFunction().getC());
            else out.println("// decompile failed: " + res.getErrorMessage());
        }
        out.close();
    }
}
