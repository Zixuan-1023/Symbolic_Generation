import torch

# Variable is deprecated in PyTorch; use Tensor directly (compatible with 1.0 and 2.x)


def to_cuda_variable(tensor):
    """
    Converts tensor to cuda tensor (with grad)
    :param tensor: torch tensor, of any size
    :return: torch Tensor, of same size as tensor
    """
    if torch.cuda.is_available():
        return tensor.contiguous().cuda()
    return tensor


def to_cuda_variable_long(tensor):
    """
    Converts tensor to cuda long tensor
    :param tensor: torch tensor, of any size
    :return: torch Tensor (long), of same size as tensor
    """
    t = tensor.long()
    if torch.cuda.is_available():
        return t.contiguous().cuda()
    return t


def to_numpy(tensor):
    """
    Converts torch tensor to numpy nd array
    :param tensor: torch Tensor, of any size
    :return: numpy nd array, of same size as tensor
    """
    if tensor.is_cuda:
        return tensor.detach().cpu().numpy()
    return tensor.detach().numpy()


def init_hidden_lstm(num_layers, batch_size, lstm_hidden_size):
    hidden = (
        to_cuda_variable(
            torch.zeros(num_layers, batch_size, lstm_hidden_size)
        ),
        to_cuda_variable(
            torch.zeros(num_layers, batch_size, lstm_hidden_size)
        )
    )
    return hidden
