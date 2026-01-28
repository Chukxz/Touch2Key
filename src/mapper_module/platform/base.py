from abc import ABC, abstractmethod

class InputBridge(ABC):
    """
    Base interface for injecting input across different platforms.
    """
    
    @abstractmethod
    def key_down(self, code: int) -> None:
        """Press a keyboard key."""
        pass

    @abstractmethod
    def key_up(self, code: int) -> None:
        """Release a keyboard key."""
        pass

    @abstractmethod
    def mouse_move_rel(self, dx: int, dy: int) -> None:
        """Relative mouse move."""
        pass

    @abstractmethod
    def mouse_move_abs(self, x: int, y: int) -> None:
        """Absolute mouse move."""
        pass

    @abstractmethod
    def left_click_down(self) -> None:
        """Left mouse button down."""
        pass

    @abstractmethod
    def left_click_up(self) -> None:
        """Left mouse button up."""
        pass

    @abstractmethod
    def right_click_down(self) -> None:
        """Right mouse button down."""
        pass

    @abstractmethod
    def right_click_up(self) -> None:
        """Right mouse button up."""
        pass

    @abstractmethod
    def middle_click_down(self) -> None:
        """Middle mouse button down."""
        pass

    @abstractmethod
    def middle_click_up(self) -> None:
        """Middle mouse button up."""
        pass

    @abstractmethod
    def release_all(self) -> None:
        """Emergency release for all keys and buttons."""
        pass
