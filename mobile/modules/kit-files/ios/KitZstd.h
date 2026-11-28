// What Books.swift calls in zstd's decoder (zstddeclib.c), as zstd.h declares it
#pragma once
#include <stddef.h>

typedef struct ZSTD_DCtx_s ZSTD_DCtx;
typedef struct ZSTD_inBuffer_s {
  const void *src;
  size_t size;
  size_t pos;
} ZSTD_inBuffer;
typedef struct ZSTD_outBuffer_s {
  void *dst;
  size_t size;
  size_t pos;
} ZSTD_outBuffer;

ZSTD_DCtx *ZSTD_createDCtx(void);
size_t ZSTD_freeDCtx(ZSTD_DCtx *dctx);
size_t ZSTD_decompressStream(ZSTD_DCtx *zds, ZSTD_outBuffer *output, ZSTD_inBuffer *input);
unsigned ZSTD_isError(size_t result);
