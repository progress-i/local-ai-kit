;; WASI capability boundary: fd 3 is the sole preopened directory (/work).
;; The module has no process, network, environment or Python callbacks.
(module
  (import "wasi_snapshot_preview1" "path_open"
    (func $open (param i32 i32 i32 i32 i32 i64 i64 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_read"
    (func $read (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_write"
    (func $write (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_close"
    (func $close (param i32) (result i32)))
  (memory (export "memory") 1 1)
  ;; path bytes at 1024; write bytes at 4096; read bytes at 16384.
  ;; errno returned to host; result byte count at address 16.
  (func (export "run") (param $mode i32) (param $pathlen i32) (param $length i32) (result i32)
    (local $err i32) (local $fd i32)
    (if (i32.gt_u (local.get $pathlen) (i32.const 512))
      (then (return (i32.const 28))))
    (if (i32.gt_u (local.get $length) (i32.const 8193))
      (then (return (i32.const 28))))
    (local.set $err
      (call $open (i32.const 3) (i32.const 0) (i32.const 1024) (local.get $pathlen)
        ;; CREAT | EXCL for writing: existing files can never be overwritten.
        (if (result i32) (local.get $mode) (then (i32.const 5)) (else (i32.const 0)))
        (if (result i64) (local.get $mode) (then (i64.const 64)) (else (i64.const 2)))
        (i64.const 0) (i32.const 0) (i32.const 0)))
    (if (local.get $err) (then (return (local.get $err))))
    (local.set $fd (i32.load (i32.const 0)))
    (i32.store (i32.const 8)
      (if (result i32) (local.get $mode) (then (i32.const 4096)) (else (i32.const 16384))))
    (i32.store (i32.const 12) (local.get $length))
    (local.set $err
      (if (result i32) (local.get $mode)
        (then (call $write (local.get $fd) (i32.const 8) (i32.const 1) (i32.const 16)))
        (else (call $read (local.get $fd) (i32.const 8) (i32.const 1) (i32.const 16)))))
    (drop (call $close (local.get $fd)))
    (local.get $err))
)
