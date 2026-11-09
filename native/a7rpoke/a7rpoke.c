/*
 * a7rpoke: guarded byte patch of a file at an offset (e.g. /proc/<pid>/mem).
 *
 *   a7rpoke FILE OFFSET OLDHEX NEWHEX   write NEWHEX only if FILE holds OLDHEX
 *   a7rpoke FILE OFFSET --read N        print N bytes as hex
 *
 * Exit codes: 0 ok (written, or already NEWHEX), 1 usage/IO error,
 * 2 contents differ from OLDHEX (nothing written), 3 verify after write failed.
 * Built static for the camera (ARMv7) and for the host tests with zig cc.
 */
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MAXLEN 64

static int parse_hex(const char *s, unsigned char *out, size_t *len)
{
    size_t n = strlen(s);
    if (n == 0 || n % 2 || n / 2 > MAXLEN)
        return -1;
    for (size_t i = 0; i < n / 2; i++) {
        unsigned v;
        if (sscanf(s + 2 * i, "%2x", &v) != 1)
            return -1;
        for (int k = 0; k < 2; k++) {
            char c = s[2 * i + k];
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')))
                return -1;
        }
        out[i] = (unsigned char)v;
    }
    *len = n / 2;
    return 0;
}

static void print_hex(const char *label, const unsigned char *b, size_t n)
{
    printf("%s", label);
    for (size_t i = 0; i < n; i++)
        printf("%02x", b[i]);
    printf("\n");
}

static int read_at(int fd, off_t off, unsigned char *buf, size_t n)
{
    ssize_t r = pread(fd, buf, n, off);
    if (r != (ssize_t)n) {
        fprintf(stderr, "pread: %s\n", r < 0 ? strerror(errno) : "short read");
        return -1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 5) {
        fprintf(stderr, "usage: a7rpoke FILE OFFSET OLDHEX NEWHEX | FILE OFFSET --read N\n");
        return 1;
    }
    char *end;
    errno = 0;
    unsigned long long off = strtoull(argv[2], &end, 0);
    if (errno || *end) {
        fprintf(stderr, "bad offset\n");
        return 1;
    }

    unsigned char cur[MAXLEN], old[MAXLEN], new_[MAXLEN];
    size_t n_old, n_new;

    if (strcmp(argv[3], "--read") == 0) {
        long n = strtol(argv[4], &end, 10);
        if (*end || n <= 0 || n > MAXLEN) {
            fprintf(stderr, "bad length\n");
            return 1;
        }
        int fd = open(argv[1], O_RDONLY);
        if (fd < 0 || read_at(fd, (off_t)off, cur, (size_t)n) < 0) {
            perror("open/read");
            return 1;
        }
        print_hex("read ", cur, (size_t)n);
        close(fd);
        return 0;
    }

    if (parse_hex(argv[3], old, &n_old) || parse_hex(argv[4], new_, &n_new) || n_old != n_new) {
        fprintf(stderr, "OLDHEX and NEWHEX must be hex of equal length (max %d bytes)\n", MAXLEN);
        return 1;
    }

    int fd = open(argv[1], O_RDWR);
    if (fd < 0) {
        perror("open");
        return 1;
    }
    if (read_at(fd, (off_t)off, cur, n_old) < 0)
        return 1;
    print_hex("before ", cur, n_old);

    if (memcmp(cur, new_, n_old) == 0) {
        printf("already patched\n");
        close(fd);
        return 0;
    }
    if (memcmp(cur, old, n_old) != 0) {
        printf("contents differ from expected original, nothing written\n");
        close(fd);
        return 2;
    }
    ssize_t w = pwrite(fd, new_, n_new, (off_t)off);
    if (w != (ssize_t)n_new) {
        fprintf(stderr, "pwrite: %s\n", w < 0 ? strerror(errno) : "short write");
        close(fd);
        return 1;
    }
    if (read_at(fd, (off_t)off, cur, n_new) < 0)
        return 1;
    print_hex("after ", cur, n_new);
    close(fd);
    if (memcmp(cur, new_, n_new) != 0) {
        printf("verify failed\n");
        return 3;
    }
    printf("ok\n");
    return 0;
}
