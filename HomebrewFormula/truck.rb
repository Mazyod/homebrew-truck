class Truck < Formula
  desc "Truck - the simplest dependency manager"
  url "https://github.com/Mazyod/homebrew-truck/archive/0.6.3.zip"
  version "0.6.3"
  # sha256 "85cc828a96735bdafcf29eb6291ca91bac846579bcef7308536e0c875d6c81d7"
  depends_on "python3"
  depends_on "github-release" => :recommended
  depends_on "awscli" => :optional

  def install
    bin.install "truck.py" => "truck"
  end

  test do
  end
end
