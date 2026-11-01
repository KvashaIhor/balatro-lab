// gpu_probe.m -- how fast is 64-bit integer math on this Mac's GPU?  Software double precision (the GPU
// has no fp64) is built from 64-bit multiplies (low and high halves) and 64-bit adds/shifts/compares, so
// these rates bound how fast a GPU seed scan could be.
//
// Build:  clang -O2 -fobjc-arc -framework Metal -framework Foundation gpu_probe.m -o gpu_probe
#import <Metal/Metal.h>
#include <stdio.h>

static NSString *const SRC = @
"#include <metal_stdlib>\n"
"using namespace metal;\n"
"kernel void mul64(device ulong *out [[buffer(0)]], constant uint &iters [[buffer(1)]], uint id [[thread_position_in_grid]]) {\n"
"  ulong a = 0x9E3779B97F4A7C15ul ^ id, b = 0xBF58476D1CE4E5B9ul + id, c = 0x94D049BB133111EBul, d = id * 7ul + 1;\n"
"  for (uint i = 0; i < iters; i++) {\n"           // 4 independent chains, each: one full 64x64 multiply (lo + hi)
"    a = (a * c) ^ mulhi(a, c); b = (b * c) ^ mulhi(b, c); d = (d * c) ^ mulhi(d, c); c = (c * a) ^ mulhi(c, b);\n"
"  }\n"
"  out[id] = a ^ b ^ c ^ d;\n"
"}\n"
"kernel void add64(device ulong *out [[buffer(0)]], constant uint &iters [[buffer(1)]], uint id [[thread_position_in_grid]]) {\n"
"  ulong a = 0x9E3779B97F4A7C15ul ^ id, b = id, c = 0x94D049BB133111EBul, d = ~(ulong)id;\n"
"  for (uint i = 0; i < iters; i++) {\n"           // 4 chains x 4 ops: add, shift, xor, compare-select
"    a = (a + b) ^ (a >> 7); a = a < c ? a + d : a - d;\n"
"    b = (b + c) ^ (b << 9); b = b < a ? b + 1 : b ^ c;\n"
"    c = (c + d) ^ (c >> 13); c = c < b ? c + a : c - 3;\n"
"    d = (d + a) ^ (d << 5); d = d < c ? d + b : d ^ a;\n"
"  }\n"
"  out[id] = a ^ b ^ c ^ d;\n"
"}\n"
"kernel void fma32(device float *out [[buffer(0)]], constant uint &iters [[buffer(1)]], uint id [[thread_position_in_grid]]) {\n"
"  float a = id * 1e-7f, b = 0.5f, c = 1.0001f, d = 0.25f;\n"
"  for (uint i = 0; i < iters; i++) { a = fma(a, c, b); b = fma(b, c, d); d = fma(d, c, a); c = fma(c, 0.99999f, 1e-6f); }\n"
"  out[id] = a + b + c + d;\n"
"}\n";

int main(void) {
    @autoreleasepool {
        id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
        NSError *err = nil;
        id<MTLLibrary> lib = [dev newLibraryWithSource:SRC options:nil error:&err];
        if (!lib) { printf("compile failed: %s\n", [[err description] UTF8String]); return 1; }
        id<MTLCommandQueue> q = [dev newCommandQueue];
        const NSUInteger threads = 40 * 1024 * 64;    // plenty of threads for 40 GPU cores
        id<MTLBuffer> out = [dev newBufferWithLength:threads * 8 options:MTLResourceStorageModeShared];
        struct { const char *name; double ops_per_iter; const char *unit; } tests[] = {
            {"mul64", 4, "64-bit multiplies (low+high)"}, {"add64", 16, "64-bit add/shift/xor/select ops"},
            {"fma32", 4, "fp32 fused multiply-adds"}};
        for (int k = 0; k < 3; k++) {
            id<MTLFunction> fn = [lib newFunctionWithName:[NSString stringWithUTF8String:tests[k].name]];
            id<MTLComputePipelineState> ps = [dev newComputePipelineStateWithFunction:fn error:&err];
            uint32_t iters = 2000;
            double best = 1e9;
            for (int rep = 0; rep < 3; rep++) {
                id<MTLCommandBuffer> cb = [q commandBuffer];
                id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
                [enc setComputePipelineState:ps];
                [enc setBuffer:out offset:0 atIndex:0];
                [enc setBytes:&iters length:4 atIndex:1];
                [enc dispatchThreads:MTLSizeMake(threads, 1, 1) threadsPerThreadgroup:MTLSizeMake(ps.maxTotalThreadsPerThreadgroup, 1, 1)];
                [enc endEncoding];
                [cb commit];
                [cb waitUntilCompleted];
                double t = cb.GPUEndTime - cb.GPUStartTime;
                if (t < best) best = t;
            }
            double ops = (double)threads * iters * tests[k].ops_per_iter;
            printf("%-6s %8.1f G %s per second  (%.3f s)\n", tests[k].name, ops / best / 1e9, tests[k].unit, best);
        }
    }
    return 0;
}
