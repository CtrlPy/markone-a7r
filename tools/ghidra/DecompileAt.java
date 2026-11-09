// Decompile the function containing an ELF virtual address (image base is added).
// Usage (headless, -process): -postScript DecompileAt.java <elf_vaddr_hex> <outfile>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.*;

public class DecompileAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        long vaddr = Long.parseLong(args[0].replace("0x", ""), 16);
        Address a = currentProgram.getImageBase().add(vaddr);
        PrintWriter out = new PrintWriter(new FileWriter(args[1]));
        Function f = getFunctionContaining(a);
        out.println("// image base " + currentProgram.getImageBase() + ", address " + a);
        if (f == null) { out.println("// no function"); out.close(); return; }
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        DecompileResults r = dec.decompileFunction(f, 120, monitor);
        out.println("// " + f.getName(true) + " @ " + f.getEntryPoint());
        out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// failed " + r.getErrorMessage());
        out.close();
    }
}
