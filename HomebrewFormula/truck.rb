class Truck < Formula
  desc "Truck."
  url "https://github.com/mazyod/homebrew-truck"
  version "0.0.1"

  def install
    bin.install "truck-client.py" => "truck"
  end

  test do
  end
end
