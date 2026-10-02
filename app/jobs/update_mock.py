from app.mock import data
from app.mock import group
from app.mock import function


def update_data() -> None:
    print("Updating data.txt + group.txt...")

    data.build()
    group.build()

    function.reload()

    print("Update completed")
