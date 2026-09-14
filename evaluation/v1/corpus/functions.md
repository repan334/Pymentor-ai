# Fungsi Python

Pernyataan `return` menghentikan eksekusi fungsi dan mengirimkan nilai kepada
pemanggil. Jika eksekusi mencapai akhir fungsi tanpa `return` eksplisit, Python
mengembalikan `None`.

Contoh:

```python
def salam(nama):
    return f"Halo, {nama}"
```

Fungsi dapat tampak mengembalikan beberapa nilai dengan menuliskannya dipisahkan
koma. Python sebenarnya mengemas nilai-nilai tersebut menjadi satu tuple.
