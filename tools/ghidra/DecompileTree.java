// Decompile functions whose name contains a pattern, and their callees up to a depth.
// Usage: -postScript DecompileTree.java <pattern> <depth> <outfile>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.Function;
import java.io.*;
import java.util.*;

public class DecompileTree extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        String pattern = a[0];
        int depth = Integer.parseInt(a[1]);
        PrintWriter out = new PrintWriter(new FileWriter(a[2]));
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Deque<Object[]> q = new ArrayDeque<>();
        Set<Function> seen = new HashSet<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true))
            if (f.getName(true).contains(pattern) && !f.isExternal()) q.add(new Object[]{f, 0});
        while (!q.isEmpty()) {
            Object[] e = q.poll();
            Function f = (Function) e[0];
            int d = (Integer) e[1];
            if (f.isThunk()) f = f.getThunkedFunction(true);
            if (f == null || f.isExternal() || !seen.add(f)) continue;
            DecompileResults r = dec.decompileFunction(f, 120, monitor);
            out.println("\n// ===== depth " + d + " " + f.getName(true) + " @ " + f.getEntryPoint());
            out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// failed");
            if (d < depth)
                for (Function c : f.getCalledFunctions(monitor)) q.add(new Object[]{c, d + 1});
        }
        out.close();
    }
}
